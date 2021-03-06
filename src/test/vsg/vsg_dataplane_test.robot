# Copyright 2018-present Open Networking Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

*** Settings ***
Suite Setup       Setup
Suite Teardown    Teardown
Test Timeout      10 minutes
Documentation     Validates external connectivity from Cord-Tester Container through VSG Subscriber
Library           OperatingSystem
Library           SSHLibrary
Library           /opt/cord/test/cord-tester/src/test/cord-api/Framework/utils/utils.py
Library           /opt/cord/test/cord-tester/src/test/cord-api/Framework/utils/onosUtils.py
Library           /opt/cord/test/cord-tester/src/test/cord-api/Framework/utils/openstackUtils.py
Resource          /opt/cord/test/cord-tester/src/test/cord-api/Framework/utils/utils.robot

*** Variables ***
${pod}              qct-pod1.yml
${vsg_data_file}    /opt/cord/test/cord-tester/src/test/cord-api/Tests/data/Ch_Subscriber.json

*** Test Cases ***
Validate Instances are ACTIVE
    [Documentation]    Validates that all instances are ACTIVE
    Wait Until Keyword Succeeds    300s    5s    Instances ACTIVE

Validate Connectivity to All VSGs via Mgmt Interface
    [Documentation]    Validates that all given vsg instances are reachable through the mgmt interfaces
    ##Loop through nova ids,  get mgmt ips + compute nodes, ssh into compute node, and validate ping to mgmt_ip
    : FOR    ${nova_id}    IN    @{nova_ids}
    \    ${mgmt_ip}=    Run    . /opt/cord_profile/admin-openrc.sh; nova show ${nova_id} | grep management | awk '{print $5}'
    \    ${node}=    Run    . /opt/cord_profile/admin-openrc.sh; nova show ${nova_id} | grep :host | awk '{print $4}'
    \    ${ping_result}=    Run    ssh ubuntu@${node} ping -c 1 ${mgmt_ip}
    \    Should Contain   ${ping_result}    64 bytes from ${mgmt_ip}
    \    Should Not Contain    ${ping_result}    100% packet loss

Validate VSG External Connectivity
    [Documentation]    Validates that the given vsg instances have external connectivity
    : FOR    ${nova_id}    IN    @{nova_ids}
    \    ${mgmt_ip}=    Run    . /opt/cord_profile/admin-openrc.sh; nova show ${nova_id} | grep management | awk '{print $5}'
    \    ${node}=    Run    . /opt/cord_profile/admin-openrc.sh; nova show ${nova_id} | grep :host | awk '{print $4}'
    \    Wait Until Keyword Succeeds    300s    5s    Validate Ext Connectivity    ${node}    ${mgmt_ip}

Configure X-Connects for 3 Subscribers
    [Documentation]    Configures the cross connect on the fabric switch with s-tags for the subscribers created via control-plane tests on the correct ports
    [Tags]    xconnect    dataplane
    ${netcfg_init}=    onosUtils.onos_command_execute    onos-fabric    8101    netcfg
    Log    ${netcfg_init}
    Run    http -a onos:rocks DELETE http://onos-fabric:8181/onos/v1/network/configuration/
    Sleep    15
    Run    http -a onos:rocks POST http://onos-fabric:8181/onos/v1/network/configuration/ < /opt/cord/test/cord-tester/src/test/setup/${netcfg_file}
    Sleep    15
    Run    http -a onos:rocks DELETE http://onos-fabric:8181/onos/v1/applications/org.onosproject.segmentrouting/active
    Sleep    15
    Run    http -a onos:rocks POST http://onos-fabric:8181/onos/v1/applications/org.onosproject.segmentrouting/active
    Sleep    15
    ${netcfg}=    onosUtils.onos_command_execute    onos-fabric    8101    netcfg
    Log    ${netcfg}
    Should Contain    ${netcfg}    vsg-1
    Should Contain    ${netcfg}    vsg-2
    Should Contain    ${netcfg}    vsg-3
    Should Contain    ${netcfg}    "vlan" : ${s_tags[0]}
    Should Contain    ${netcfg}    "vlan" : ${s_tags[1]}
    Should Contain    ${netcfg}    "vlan" : ${s_tags[2]}

Validate VSG External Connectivity Again
    [Documentation]    Validates that the given vsg instances have external connectivity even after onos-fabric has been re-configured
    : FOR    ${nova_id}    IN    @{nova_ids}
    \    ${mgmt_ip}=    Run    . /opt/cord_profile/admin-openrc.sh; nova show ${nova_id} | grep management | awk '{print $5}'
    \    ${node}=    Run    . /opt/cord_profile/admin-openrc.sh; nova show ${nova_id} | grep :host | awk '{print $4}'
    \    Wait Until Keyword Succeeds    300s    5s    Validate Ext Connectivity    ${node}    ${mgmt_ip}

Validate VCPE Containers
    [Documentation]    Validates that vcpes containers are up in each vsg instance
    : FOR    ${nova_id}    IN    @{nova_ids}
    \    ${mgmt_ip}=    Run    . /opt/cord_profile/admin-openrc.sh; nova show ${nova_id} | grep management | awk '{print $5}'
    \    ${node}=    Run    . /opt/cord_profile/admin-openrc.sh; nova show ${nova_id} | grep :host | awk '{print $4}'
    \    Wait Until Keyword Succeeds    800s    5s    Validate VCPE Container is Up    ${node}    ${mgmt_ip}

Get VSG Subscriber and Tags
    [Documentation]    Retrieves compute node connected on leaf-1 and s/c tags for that particular subscriber
    [Tags]    dataplane
    ${cmd}=    Set Variable    cordvtn-nodes | grep 10.6.1
    ${cnode}=    onosUtils.onos_command_execute    onos-cord    8102    ${cmd}
    @{cnode_on_leaf_1}=    Split String    ${cnode}
    ${novalist}=    Run    . /opt/cord_profile/admin-openrc.sh; nova list --all-tenants | awk '{print $2}' | grep '[a-z]'
    Log    ${novalist}
    @{nova_ids}=    Split To Lines    ${novalist}
    : FOR    ${nova_id}    IN    @{nova_ids}
    \    ${node}=    Run    . /opt/cord_profile/admin-openrc.sh; nova show ${nova_id} | grep :host | awk '{print $4}'
    \    Run Keyword If    '${node}' == '${cnode_on_leaf_1[0]}'    Exit For Loop
    ${mgmt_ip}=    Run    . /opt/cord_profile/admin-openrc.sh; nova show ${nova_id} | grep management | awk '{print $5}'
    ## Get s/c tags for vsg
    ${result}=    Run    ssh -o ProxyCommand="ssh -W %h:%p -l ubuntu ${cnode_on_leaf_1[0]}" ubuntu@${mgmt_ip} "sudo docker ps|grep 'vsg\\|vcpe'" | awk '{print $10}'
    @{tags}=    Split String    ${result}    -
    ${s_tag}=    Set Variable    ${tags[1]}
    ${c_tag}=    Set Variable    ${tags[2]}
    Set Suite Variable    ${s_tag}
    Set Suite Variable    ${c_tag}

Execute Dataplane Test
    [Documentation]    Configures interfaces on cord-tester container to connect to vsg instance and validates traffic
    [Tags]    dataplane
    ${i_num}=    Set Variable If
    ...    '${s_tag}' == '${s_tags[0]}'    1
    ...    '${s_tag}' == '${s_tags[1]}'    2
    ...    '${s_tag}' == '${s_tags[2]}'    3
    ${output}=    Run    docker exec cord-tester1 bash -c "sudo echo 'nameserver 192.168.0.1' > /etc/resolv.conf"
    ${output}=    Run    docker exec cord-tester1 bash -c "sudo dhclient vcpe${i_num}.${s_tag}.${c_tag}"
    Sleep    5
    ${output}=    Run    docker exec cord-tester1 bash -c "sudo route add default gw 192.168.0.1 vcpe${i_num}.${s_tag}.${c_tag}"
    ${output}=    Run    docker exec cord-tester1 bash -c "ping -c 3 -I vcpe${i_num}.${s_tag}.${c_tag} 8.8.8.8"
    Log To Console    \n ${output}
    Should Contain   ${output}    64 bytes from 8.8.8.8
    Should Not Contain    ${output}    100% packet loss

*** Keywords ***
Setup
    [Documentation]    Gets global vars for test suite
    @{s_tags}=    Create List
    @{c_tags}=    Create List
    ${netcfg_file}=    Set Variable If
    ...    '${pod}' == 'qct-pod1.yml'    qct_fabric_test_netcfg.json
    ...    '${pod}' == 'flex-pod1.yml'    flex_fabric_test_netcfg.json
    ...    '${pod}' == 'calix-pod1.yml'    calix_fabric_test_netcfg.json
    Set Suite Variable    ${netcfg_file}
    ${subscriberList} =    utils.jsonToList    ${vsg_data_file}    SubscriberInfo
    Set Suite Variable    ${slist}    ${subscriberList}
    ${voltTenantList} =    Get Variable Value    ${slist}
    ${vsg_count}=    Get Length    ${slist}
    Set Suite Variable    ${vsg_count}
    : FOR    ${INDEX}    IN RANGE    0    ${vsg_count}
    \    ${s_tag}=    Get From Dictionary    ${slist[${INDEX}]}    s_tag
    \    ${c_tag}=    Get From Dictionary    ${slist[${INDEX}]}    c_tag
    \    Append To List    ${s_tags}    ${s_tag}
    \    Append To List    ${c_tags}    ${c_tag}
    @{nova_ids}=    Wait Until Keyword Succeeds    120s    5s    Validate Number of VSGs    ${vsg_count}
    Set Suite Variable    @{nova_ids}
    Set Suite Variable    ${s_tags}
    Set Suite Variable    ${c_tags}

Teardown
    ${cmd}=    Set Variable    log:display
    ${onos_logs}=    onosUtils.onos_command_execute    onos-fabric    8101    ${cmd}
    Log    ${onos_logs}

Validate Number of VSGs
    [Arguments]    ${count}
    ${novalist}=    Run    . /opt/cord_profile/admin-openrc.sh; nova list --all-tenants | awk '{print $2}' | grep '[a-z]'
    Log    ${novalist}
    @{nova_ids}=    Split To Lines    ${novalist}
    ${vsgCount}=    Get Length    ${nova_ids}
    Should Be Equal    ${vsgCount}    ${count}
    [Return]    @{nova_ids}

Instances ACTIVE
    : FOR    ${nova_id}    IN    @{nova_ids}
    \    ${status}=    Run    . /opt/cord_profile/admin-openrc.sh; nova show ${nova_id} | grep status | awk '{print $4}'
    \    Should Be Equal    ${status}    ACTIVE

Validate Ext Connectivity
    [Arguments]    ${compute_node}    ${vsg_ip}
    ${ping_ext_result}=    Run    ssh -o ProxyCommand="ssh -W %h:%p -l ubuntu ${compute_node}" ubuntu@${vsg_ip} "ping -c 3 8.8.8.8"
    Should Contain   ${ping_ext_result}    64 bytes from 8.8.8.8
    Should Not Contain    ${ping_ext_result}    100% packet loss

Validate VCPE Container is Up
    [Arguments]    ${compute_node}    ${vsg_ip}
    ${docker_containers}=    Run    ssh -o ProxyCommand="ssh -W %h:%p -l ubuntu ${compute_node}" ubuntu@${vsg_ip} sudo docker ps | wc -l
    Should Not Contain   ${docker_containers}    0
