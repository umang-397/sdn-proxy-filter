
#!/usr/bin/env python3

import os
import time
import argparse

from mininet.net import Mininet
from mininet.topo import Topo
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ProxyFilterTopo(Topo):

    def build(self):

        # Create the Open vSwitch
        s1 = self.addSwitch(
            "s1",
            protocols="OpenFlow13"
        )

        # Create client hosts
        c1 = self.addHost("c1", ip="10.0.0.1/24")
        c2 = self.addHost("c2", ip="10.0.0.2/24")
        c3 = self.addHost("c3", ip="10.0.0.3/24")

        # Create proxy host
        proxy = self.addHost("proxy", ip="10.0.0.10/24")

        # Create service hosts
        web = self.addHost("web", ip="10.0.0.21/24")
        files = self.addHost("files", ip="10.0.0.22/24")

        # Connect every host to the switch
        for host in [c1, c2, c3, proxy, web, files]:
            self.addLink(host, s1)


def start_applications(net):

    info("\n*** Starting web service\n")
    web = net.get("web")
    web.cmd(
        "cd %s && python3 app/service.py "
        "--name web --port 8001 > logs/web.log 2>&1 &" % PROJECT_DIR
    )

    info("*** Starting files service\n")
    files = net.get("files")
    files.cmd(
        "cd %s && python3 app/service.py "
        "--name files --port 8002 > logs/files.log 2>&1 &" % PROJECT_DIR
    )

    info("*** Starting TCP proxy\n")
    proxy = net.get("proxy")
    proxy.cmd(
        "cd %s && python3 app/proxy.py "
        "> logs/proxy.log 2>&1 &" % PROJECT_DIR
    )

    time.sleep(2)
    info("*** Applications started\n")


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--controller-ip", default="127.0.0.1")
    parser.add_argument("--controller-port", type=int, default=6653)
    args = parser.parse_args()

    os.makedirs(os.path.join(PROJECT_DIR, "logs"), exist_ok=True)

    topo = ProxyFilterTopo()

    net = Mininet(
        topo=topo,
        controller=None,
        switch=OVSSwitch,
        autoSetMacs=True,
        waitConnected=True
    )

    net.addController(
        "c0",
        controller=RemoteController,
        ip=args.controller_ip,
        port=args.controller_port
    )

    try:
        info("\n*** Starting network\n")
        net.start()

        start_applications(net)

        info("\n*** Network is ready\n")
        info("*** Hosts: c1 c2 c3 proxy web files\n")
        info("*** Switch: s1 (OpenFlow 1.3)\n")
        info("*** Enter Mininet commands below\n\n")

        CLI(net)

    finally:
        info("\n*** Stopping network\n")
        net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    main()
