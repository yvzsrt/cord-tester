import threading
import sys
import os
import time
import monotonic
import random
from scapy.all import *
from McastTraffic import *
from IGMP import *
from OnosCtrl import OnosCtrl
from nose.tools import *
log.setLevel('DEBUG')

conf.verb = 0

class IgmpChannel:

    IGMP_DST_MAC = "01:00:5e:00:01:01"
    IGMP_SRC_MAC = "5a:e1:ac:ec:4d:a1"
    IP_SRC = '1.2.3.4'
    IP_DST = '224.0.1.1'
    igmp_eth = Ether(dst = IGMP_DST_MAC, src = IGMP_SRC_MAC, type = ETH_P_IP)
    igmp_ip = IP(dst = IP_DST, src = IP_SRC)

    def __init__(self, iface = 'veth0', src_list = ['1.2.3.4'], delay = 2):
        self.iface = iface
        self.src_list = src_list
        self.delay = delay
        self.onos_ctrl = OnosCtrl('org.onosproject.igmp')
        self.onos_ctrl.activate()

    def igmp_load_ssm_config(self, groups):
        self.ssm_table_load(groups)

    def igmp_join(self, groups, ssm_load = False):
        if ssm_load:
            self.igmp_load_ssm_config(groups)
        igmp = IGMPv3(type = IGMP_TYPE_V3_MEMBERSHIP_REPORT, max_resp_code=30,
                      gaddr='224.0.1.1')
        for g in groups:
              gr = IGMPv3gr(rtype=IGMP_V3_GR_TYPE_EXCLUDE, mcaddr=g)
              gr.sources = self.src_list
              igmp.grps.append(gr)

        pkt = self.igmp_eth/self.igmp_ip/igmp
        IGMPv3.fixup(pkt)
        sendp(pkt, iface=self.iface)
        if self.delay != 0:
            time.sleep(self.delay)

    def igmp_leave(self, groups):
        igmp = IGMPv3(type = IGMP_TYPE_V3_MEMBERSHIP_REPORT, max_resp_code=30,
                      gaddr='224.0.1.1')
        for g in groups:
              gr = IGMPv3gr(rtype=IGMP_V3_GR_TYPE_INCLUDE, mcaddr=g)
              gr.sources = self.src_list
              igmp.grps.append(gr)

        pkt = self.igmp_eth/self.igmp_ip/igmp
        IGMPv3.fixup(pkt)
        sendp(pkt, iface = self.iface)
        if self.delay != 0:
            time.sleep(self.delay)

    def onos_load_config(self, config):
        status, code = self.onos_ctrl.config(config)
        if status is False:
            log.info('JSON config request for app %s returned status %d' %code)
        time.sleep(2)

    def ssm_table_load(self, groups):
          ssm_dict = {'apps' : { 'org.onosproject.igmp' : { 'ssmTranslate' : [] } } }
          ssm_xlate_list = ssm_dict['apps']['org.onosproject.igmp']['ssmTranslate']
          for g in groups:
                for s in self.src_list:
                      d = {}
                      d['source'] = s
                      d['group'] = g
                      ssm_xlate_list.append(d)
          self.onos_load_config(ssm_dict)

class Channels(IgmpChannel):
    Stopped = 0
    Started = 1
    Idle = 0
    Joined = 1
    def __init__(self, num, iface = 'veth0', iface_mcast = 'veth2', mcast_cb = None):
        self.num = num
        self.channels = self.generate(self.num)
        self.group_channel_map = {}
        for i in range(self.num):
            self.group_channel_map[self.channels[i]] = i
        self.state = self.Stopped
        self.streams = None
        self.channel_states = {}
        self.last_chan = None
        self.recv_sock = L2Socket(iface = iface, type = ETH_P_IP)
        self.iface_mcast = iface_mcast
        self.mcast_cb = mcast_cb
        for c in range(self.num):
            self.channel_states[c] = [self.Idle]

        IgmpChannel.__init__(self, iface=iface)

    def generate(self, num):
        start = (224 << 24) | 1
        end = start + num + num/256 
        group_addrs = []
        for i in range(start, end):
            if i&255:
                g = '%s.%s.%s.%s' %((i>>24) &0xff, (i>>16)&0xff, (i>>8)&0xff, i&0xff)
                log.debug('Adding group %s' %g)
                group_addrs.append(g)
        return group_addrs

    def start(self):
        if self.state == self.Stopped:
            if self.streams:
                self.streams.stop()
            self.streams = McastTraffic(self.channels, iface=self.iface_mcast, cb = self.mcast_cb)
            self.streams.start()
            self.state = self.Started

    def join(self, chan = None):
        if chan is None:
            chan = random.randint(0, self.num)
        else:
            if chan >= self.num:
                chan = 0

        if self.get_state(chan) == self.Joined:
            return chan, 0

        groups = [self.channels[chan]]
        #load the ssm table first
        self.igmp_load_ssm_config(groups)
        join_start = monotonic.monotonic()
        self.igmp_join(groups)
        self.set_state(chan, self.Joined)
        self.last_chan = chan
        return chan, join_start

    def leave(self, chan):
        if chan is None:
            chan = self.last_chan
        if chan is None or chan >= self.num:
            return False
        if self.get_state(chan) != self.Joined:
            return False
        groups = [self.channels[chan]]
        self.igmp_leave(groups)
        self.set_state(chan, self.Idle)
        if chan == self.last_chan:
            self.last_chan = None
        return True
    
    def join_next(self, chan = None):
        if chan is None:
            chan = self.last_chan
            if chan is None:
                return None
            leave = chan
            join = chan+1
        else:
            leave = chan - 1
            join = chan
        
        if join >= self.num:
            join = 0

        if leave >= 0 and leave != join:
            self.leave(leave)

        return self.join(join)

    def jump(self):
        chan = self.last_chan
        if chan is not None:
            self.leave(chan)
            s_next = chan
        else:
            s_next = 0
        if self.num - s_next < 2:
            s_next = 0
        chan = random.randint(s_next, self.num)
        return self.join(chan)

    def gaddr(self, chan):
        '''Return the group address for a channel'''
        if chan >= self.num:
            return None
        return self.channels[chan]

    def caddr(self, group):
        '''Return a channel given a group addr'''
        if self.group_channel_map.has_key(group):
            return self.group_channel_map[group]
        return None

    def recv_cb(self, pkt):
        '''Default channel receive callback'''
        log.debug('Received packet from source %s, destination %s' %(pkt[IP].src, pkt[IP].dst))
        send_time = float(pkt[IP].payload.load)
        recv_time = monotonic.monotonic()
        log.debug('Packet received in %.3f usecs' %(recv_time - send_time))

    def recv(self, chan, cb = None, count = 1):
        if chan is None:
            return None
        if type(chan) == type([]) or type(chan) == type(()):
            channel_list=filter(lambda c: c < self.num, chan)
            groups = map(lambda c: self.gaddr(c), channel_list)
        else:
            groups = (self.gaddr(chan),)
        if cb is None:
            cb = self.recv_cb
        sniff(prn = cb, count=count, lfilter = lambda p: p[IP].dst in groups, opened_socket = self.recv_sock)

    def stop(self):
        if self.streams:
            self.streams.stop()
        self.state = self.Stopped

    def get_state(self, chan):
        return self.channel_states[chan][0]

    def set_state(self, chan, state):
        self.channel_states[chan][0] = state

if __name__ == '__main__':
    num = 2
    channels = Channels(num)
    channels.start()
    for i in range(num):
        channels.join(i)
    for i in range(num):
        channels.recv(i)
    for i in range(num):
        channels.leave(i)
    channels.stop()
