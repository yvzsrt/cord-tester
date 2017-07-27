import requests
import json
import time
import os
import signal
from CordTestUtils import log_test as log, getstatusoutput, get_controller
from CordContainer import Container, Onos
from OnosCtrl import OnosCtrl
from OltConfig import OltConfig

class VolthaService(object):
    services = ('consul', 'kafka', 'zookeeper', 'registrator', 'fluentd')
    compose_file = 'docker-compose-system-test.yml'
    service_map = {}

    def __init__(self, voltha_loc, controller, interface = 'eth0', olt_config = None):
        if not os.access(voltha_loc, os.F_OK):
            raise Exception('Voltha location %s not found' %voltha_loc)
        compose_file_loc = os.path.join(voltha_loc, 'compose', self.compose_file)
        if not os.access(compose_file_loc, os.F_OK):
            raise Exception('Voltha compose file %s not found' %compose_file_loc)
        self.voltha_loc = voltha_loc
        self.controller = controller
        self.interface = interface
        self.compose_file_loc = compose_file_loc
        num_onus = 1
        if olt_config is not None:
            port_map, _ = OltConfig(olt_config).olt_port_map()
            if port_map['ponsim'] is True:
                num_onus = max(1, len(port_map['ports']))
        self.num_onus = num_onus

    def start(self):
        start_cmd = 'docker-compose -f {} up -d {} {} {} {} {}'.format(self.compose_file_loc,
                                                                       *self.services)
        ret = os.system(start_cmd)
        if ret != 0:
            raise Exception('Failed to start voltha services. Failed with code %d' %ret)

        for service in self.services:
            name = 'compose_{}_1'.format(service)
            network = 'compose_default'
            cnt = Container(name, name)
            ip = cnt.ip(network = network)
            if not ip:
                raise Exception('IP not found for container %s' %name)
            print('IP %s for service %s' %(ip, service))
            self.service_map[service] = dict(name = name, network = network, ip = ip)

        #first start chameleon
        chameleon_start_cmd = "cd {} && sh -c '. ./env.sh && \
        nohup python chameleon/main.py -v --consul=localhost:8500 \
        --fluentd={}:24224 --grpc-endpoint=localhost:50555 \
        >/tmp/chameleon.log 2>&1 &'".format(self.voltha_loc,
                                            self.service_map['fluentd']['ip'])
        if not self.service_running('python chameleon/main.py'):
            ret = os.system(chameleon_start_cmd)
            if ret != 0:
                raise Exception('VOLTHA chameleon service not started. Failed with return code %d' %ret)
            time.sleep(10)
        else:
            print('Chameleon voltha sevice is already running. Skipped start')

        #now start voltha and ofagent
        voltha_setup_cmd = "cd {} && sh -c '. ./env.sh && make rebuild-venv && make protos'".format(self.voltha_loc)
        voltha_start_cmd = "cd {} && sh -c '. ./env.sh && \
        nohup python voltha/main.py -v --consul=localhost:8500 --kafka={}:9092 -I {} \
        --fluentd={}:24224 --rest-port=8880 --grpc-port=50555 \
        >/tmp/voltha.log 2>&1 &'".format(self.voltha_loc,
                                         self.service_map['kafka']['ip'],
                                         self.interface,
                                         self.service_map['fluentd']['ip'])
        pki_dir = '{}/pki'.format(self.voltha_loc)
        if not self.service_running('python voltha/main.py'):
            voltha_pki_dir = '/voltha'
            if os.access(pki_dir, os.F_OK):
                pki_xfer_cmd = 'mkdir -p {} && cp -rv {}/pki {}'.format(voltha_pki_dir,
                                                                        self.voltha_loc,
                                                                        voltha_pki_dir)
                os.system(pki_xfer_cmd)
            #os.system(voltha_setup_cmd)
            ret = os.system(voltha_start_cmd)
            if ret != 0:
                raise Exception('Failed to start VOLTHA. Return code %d' %ret)
            time.sleep(10)
        else:
            print('VOLTHA core is already running. Skipped start')

        ofagent_start_cmd = "cd {} && sh -c '. ./env.sh && \
        nohup python ofagent/main.py -v --consul=localhost:8500 \
        --fluentd={}:24224 --controller={}:6653 --grpc-endpoint=localhost:50555 \
        >/tmp/ofagent.log 2>&1 &'".format(self.voltha_loc,
                                          self.service_map['fluentd']['ip'],
                                          self.controller)
        if not self.service_running('python ofagent/main.py'):
            ofagent_pki_dir = '/ofagent'
            if os.access(pki_dir, os.F_OK):
                pki_xfer_cmd = 'mkdir -p {} && cp -rv {}/pki {}'.format(ofagent_pki_dir,
                                                                        self.voltha_loc,
                                                                        ofagent_pki_dir)
                os.system(pki_xfer_cmd)
            ret = os.system(ofagent_start_cmd)
            if ret != 0:
                raise Exception('VOLTHA ofagent not started. Failed with return code %d' %ret)
            time.sleep(10)
        else:
            print('VOLTHA ofagent is already running. Skipped start')

        ponsim_start_cmd = "cd {} && sh -c '. ./env.sh && \
        nohup python ponsim/main.py -o {} -v >/tmp/ponsim.log 2>&1 &'".format(self.voltha_loc, self.num_onus)
        if not self.service_running('python ponsim/main.py'):
            ret = os.system(ponsim_start_cmd)
            if ret != 0:
                raise Exception('PONSIM not started. Failed with return code %d' %ret)
            time.sleep(3)
        else:
            print('PONSIM already running. Skipped start')

    def service_running(self, pattern):
        st, _ = getstatusoutput('pgrep -f "{}"'.format(pattern))
        return True if st == 0 else False

    def kill_service(self, pattern):
        st, output = getstatusoutput('pgrep -f "{}"'.format(pattern))
        if st == 0 and output:
            pids = output.strip().splitlines()
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except:
                    pass

    def stop(self):
        self.kill_service('python voltha/main.py')
        self.kill_service('python ofagent/main.py')
        self.kill_service('python chameleon/main.py')
        self.kill_service('python ponsim/main.py')
        service_stop_cmd = 'docker-compose -f {} down'.format(self.compose_file_loc)
        os.system(service_stop_cmd)

class VolthaCtrl(object):
    UPLINK_VLAN_START = 333
    UPLINK_VLAN_MAP = { 'of:0000000000000001' : '222' }
    REST_PORT = 8881
    HOST = '172.17.0.1'

    def __init__(self, host = HOST, rest_port = REST_PORT, uplink_vlan_map = UPLINK_VLAN_MAP, uplink_vlan_start = UPLINK_VLAN_START):
        self.host = host
        self.rest_port = rest_port
        self.rest_url = 'http://{}:{}/api/v1'.format(host, rest_port)
        self.uplink_vlan_map = uplink_vlan_map
        VolthaCtrl.UPLINK_VLAN_START = uplink_vlan_start
        self.switches = []
        self.switch_map = {}

    def config(self, fake = False):
        devices = OnosCtrl.get_devices()
        if not devices:
            return self.switch_map
        voltha_devices = filter(lambda d: not d['mfr'].startswith('Nicira'), devices)
        self.switches = voltha_devices
        device_config = { 'devices' : { } }
        device_id = None
        for device in voltha_devices:
            device_id = device['id']
            ports = OnosCtrl.get_ports_device(device_id)
            nni_ports = filter(lambda p: p['isEnabled'] and 'annotations' in p and p['annotations']['portName'].startswith('nni'), ports)
            uni_ports = filter(lambda p: p['isEnabled'] and 'annotations' in p and p['annotations']['portName'].startswith('uni'), ports)
            if device_id not in self.uplink_vlan_map:
                uplink_vlan = VolthaCtrl.UPLINK_VLAN_START
                VolthaCtrl.UPLINK_VLAN_START += 1
                log.info('Voltha device %s not in map. Using uplink vlan %d' %(device_id, uplink_vlan))
            else:
                uplink_vlan = self.uplink_vlan_map[device_id]
            if not nni_ports:
                log.info('Voltha device %s has no NNI ports' %device_id)
                if fake is True:
                    log.info('Faking NNI port 0')
                    nni_ports = [ {'port': '0'} ]
                else:
                    log.info('Skip configuring device %s' %device_id)
                    continue
            if not uni_ports:
                log.info('Voltha device %s has no UNI ports' %device_id)
                if fake is True:
                    log.info('Faking UNI port 252')
                    uni_ports = [ {'port': '252'} ]
                else:
                    log.info('Skip configuring device %s' %device_id)
                    continue
            onu_ports = map(lambda uni: uni['port'], uni_ports)
            self.switch_map[device_id] = dict(uplink_vlan = uplink_vlan, ports = onu_ports)
            device_config['devices'][device_id] = {}
            device_config['devices'][device_id]['basic'] = dict(driver='pmc-olt')
            device_config['devices'][device_id]['accessDevice'] = dict(uplink=nni_ports[0]['port'],
                                                                       vlan = uplink_vlan,
                                                                       defaultVlan='0'
                                                                       )
        if device_id:
            #toggle drivers/openflow base before reconfiguring the driver and olt config data
            OnosCtrl('org.onosproject.drivers').deactivate()
            OnosCtrl('org.onosproject.openflow-base').deactivate()
            OnosCtrl.config(device_config)
            time.sleep(2)
            OnosCtrl('org.onosproject.drivers').activate()
            OnosCtrl('org.onosproject.openflow-base').activate()
            time.sleep(5)

        return self.switch_map

    def get_devices(self):
        url = '{}/local/devices'.format(self.rest_url)
        resp = requests.get(url)
        if resp.ok is not True or resp.status_code != 200:
            return None
        return resp.json()

    def enable_device(self, olt_type, olt_mac = None, address = None):
        url = '{}/local/devices'.format(self.rest_url)
        if olt_mac is None and address is None:
            log.error('Either olt mac or address needs to be specified')
            return None, False
        if olt_mac is not None:
            device_config = { 'type' : olt_type, 'mac_address' : olt_mac }
        else:
            device_config = { 'type' : olt_type, 'host_and_port' : address }
        #pre-provision
        if olt_mac is not None:
            log.info('Pre-provisioning %s with mac %s' %(olt_type, olt_mac))
        else:
            log.info('Pre-provisioning %s with address %s' %(olt_type, address))
        resp = requests.post(url, data = json.dumps(device_config))
        if resp.ok is not True or resp.status_code != 200:
            return None, False
        device_id = resp.json()['id']
        log.info('Enabling device %s' %(device_id))
        enable_url = '{}/{}/enable'.format(url, device_id)
        resp = requests.post(enable_url)
        if resp.ok is not True or resp.status_code != 200:
            return None, False
        #get operational status
        time.sleep(10)
        log.info('Checking operational status for device %s' %(device_id))
        resp = requests.get('{}/{}'.format(url, device_id))
        if resp.ok is not True or resp.status_code != 200:
            return device_id, False
        device_info = resp.json()
        if device_info['oper_status'] != 'ACTIVE' or \
           device_info['admin_state'] != 'ENABLED' or \
           device_info['connect_status'] != 'REACHABLE':
            return device_id, False

        return device_id, True

    def disable_device(self, device_id, delete = True):
        log.info('Disabling device %s' %(device_id))
        disable_url = '{}/local/devices/{}/disable'.format(self.rest_url, device_id)
        resp = requests.post(disable_url)
        if resp.ok is not True or resp.status_code != 200:
            return False
        if delete is True:
            #rest for disable completion
            time.sleep(10)
            log.info('Deleting device %s' %(device_id))
            delete_url = '{}/local/devices/{}/delete'.format(self.rest_url, device_id)
            resp = requests.delete(delete_url)
            if resp.status_code not in [204, 202, 200]:
                return False
        return True

    def restart_device(self, device_id):
        log.info('Restarting olt or onu device %s' %(device_id))
        disable_url = '{}/local/devices/{}/restart'.format(self.rest_url, device_id)
        resp = requests.post(disable_url)
        if resp.ok is not True or resp.status_code != 200:
            return False
        return True

    def pause_device(self, device_id):
        log.info('Restarting olt or onu device %s' %(device_id))
        disable_url = '{}/local/devices/{}/pause'.format(self.rest_url, device_id)
        resp = requests.post(disable_url)
        if resp.ok is not True or resp.status_code != 200:
            return False
        return True

    def get_operational_status(self, device_id):
        url = '{}/local/devices'.format(self.rest_url)
        log.info('Checking operational status for device %s' %(device_id))
        resp = requests.get('{}/{}'.format(url, device_id))
        if resp.ok is not True or resp.status_code != 200:
            return False
        device_info = resp.json()
        if device_info['oper_status'] != 'ACTIVE' or \
           device_info['admin_state'] != 'ENABLED' or \
           device_info['connect_status'] != 'REACHABLE':
           return False
        return True

    def check_preprovision_status(self, device_id):
        url = '{}/local/devices'.format(self.rest_url)
        log.info('Check if device %s is in Preprovisioning state'%(device_id))
        resp = requests.get('{}/{}'.format(url, device_id))
        if resp.ok is not True or resp.status_code != 200:
           return False
        device_info = resp.json()
        if device_info['admin_status'] == 'PREPROVISIONED':
           return True
        return False

def get_olt_app():
    our_path = os.path.dirname(os.path.realpath(__file__))
    version = Onos.getVersion()
    major = int(version.split('.')[0])
    minor = int(version.split('.')[1])
    olt_app_version = '1.2-SNAPSHOT'
    if major > 1:
        olt_app_version = '2.0-SNAPSHOT'
    elif major == 1:
        if minor > 10:
            olt_app_version = '2.0-SNAPSHOT'
        elif minor <= 8:
            olt_app_version = '1.1-SNAPSHOT'
    olt_app_file = os.path.join(our_path, '..', 'apps/olt-app-{}.oar'.format(olt_app_version))
    return olt_app_file

def voltha_setup(host = '172.17.0.1', rest_port = VolthaCtrl.REST_PORT,
                 olt_type = 'ponsim_olt', olt_mac = '00:0c:e2:31:12:00',
                 uplink_vlan_map = VolthaCtrl.UPLINK_VLAN_MAP,
                 uplink_vlan_start = VolthaCtrl.UPLINK_VLAN_START,
                 config_fake = False, olt_app = None):

    voltha = VolthaCtrl(host, rest_port = rest_port,
                        uplink_vlan_map = uplink_vlan_map,
                        uplink_vlan_start = uplink_vlan_start)
    if olt_type.startswith('ponsim'):
        ponsim_address = '{}:50060'.format(host)
        log.info('Enabling ponsim olt')
        device_id, status = voltha.enable_device(olt_type, address = ponsim_address)
    else:
        log.info('Enabling OLT instance for %s with mac %s' %(olt_type, olt_mac))
        device_id, status = voltha.enable_device(olt_type, olt_mac)

    if device_id is None or status is False:
        if device_id:
            voltha.disable_device(device_id)
        return None

    switch_map = None
    olt_installed = False
    if olt_app is None:
        olt_app = get_olt_app()
    try:
        time.sleep(5)
        switch_map = voltha.config(fake = config_fake)
        if switch_map is None:
            voltha.disable_device(device_id)
            return None
        log.info('Installing OLT app %s' %olt_app)
        OnosCtrl.install_app(olt_app)
        olt_installed = True
        time.sleep(5)
        return voltha, device_id, switch_map
    except:
        voltha.disable_device(device_id)
        time.sleep(10)
        if olt_installed is True:
            log.info('Uninstalling OLT app %s' %olt_app)
            OnosCtrl.uninstall_app(olt_app)

    return None

def voltha_teardown(voltha_ctrl, device_id, switch_map, olt_app = None):
    voltha_ctrl.disable_device(device_id)
    time.sleep(10)
    if olt_app is None:
        olt_app = get_olt_app()
    log.info('Uninstalling OLT app %s' %olt_app)
    OnosCtrl.uninstall_app(olt_app)
