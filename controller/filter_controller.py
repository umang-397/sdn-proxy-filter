"""Ryu controller for the proxy filtering project.

Default rules (priority 100):
    clients -> proxy, proxy -> clients, proxy -> services, services -> proxy
ARP is allowed (priority 100) so hosts can resolve MAC addresses.
Everything else is dropped by a priority 0 rule.

Dynamic rules (priority 200) are pushed by app/proxy.py over a unix socket:
    DROP <src> <dst>   install a drop rule
    ALLOW <src> <dst>  remove it
    CLEAR              remove every dynamic rule
    PING               return the controller's boot id
    PING               also lets the proxy detect a controller restart

The controller re-installs its known dynamic drops whenever a switch connects
or reconnects, so an OVS restart does not silently lose the policy.
"""
import json
import os
import socket
import threading
import uuid

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import (
    CONFIG_DISPATCHER,
    set_ev_cls
)
from ryu.ofproto import ofproto_v1_3

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.environ.get(
    "SDN_NETWORK_CONFIG",
    os.path.join(PROJECT_DIR, "config", "network.json")
)


class ProxyFilterController(app_manager.RyuApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(ProxyFilterController, self).__init__(*args, **kwargs)

        with open(CONFIG_PATH) as f:
            self.cfg = json.load(f)

        self.datapaths = {}
        self.dynamic_drops = set()
        self.lock = threading.RLock()
        self.boot_id = uuid.uuid4().hex[:12]
        self.socket_path = self.cfg.get("controller_sock",
                                        "/tmp/sdn_ctrl.sock")
        self.tcp = self.cfg.get("controller_tcp")

        self.logger.info("Proxy Filter Controller initialized (boot %s)",
                         self.boot_id)

        threading.Thread(
            target=self.socket_server,
            daemon=True
        ).start()

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath

        with self.lock:
            self.datapaths[datapath.id] = datapath

        self.logger.info("Switch connected: %s", datapath.id)

        self.install_default_rules(datapath)

        # A switch may reconnect (or the controller may have been restarted)
        # and start with an empty flow table.  Re-install every dynamic drop
        # that is still part of the active policy.
        with self.lock:
            drops = sorted(self.dynamic_drops)
            for src, dst in drops:
                self.add_drop_rule(datapath, src, dst)
        self.logger.info("Re-installed %d dynamic drop rule(s)",
                         len(drops))

    def add_flow(self, datapath, priority, match, actions=None):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        instructions = []

        if actions:
            instructions = [
                parser.OFPInstructionActions(
                    ofproto.OFPIT_APPLY_ACTIONS,
                    actions
                )
            ]

        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=instructions
        )

        datapath.send_msg(flow_mod)

    def install_default_rules(self, datapath):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        # Allow ARP so hosts can discover each other's MAC addresses
        match = parser.OFPMatch(
            eth_type=0x0806
        )

        actions = [
            parser.OFPActionOutput(ofproto.OFPP_NORMAL)
        ]

        self.add_flow(datapath, 100, match, actions)

        # Permitted communication pairs come from config/network.json, the
        # same file the proxy uses, so the two layers cannot drift apart.
        proxy_ip = self.cfg["proxy"]["ip"]
        clients = list(self.cfg["clients"].values())
        services = [s["ip"] for s in self.cfg["services"].values()]

        allowed_pairs = []
        allowed_pairs += [(c, proxy_ip) for c in clients]
        allowed_pairs += [(proxy_ip, c) for c in clients]
        allowed_pairs += [(proxy_ip, s) for s in services]
        allowed_pairs += [(s, proxy_ip) for s in services]

        for src, dst in allowed_pairs:
            match = parser.OFPMatch(
                eth_type=0x0800,
                ipv4_src=src,
                ipv4_dst=dst
            )

            actions = [
                parser.OFPActionOutput(ofproto.OFPP_NORMAL)
            ]

            self.add_flow(
                datapath,
                100,
                match,
                actions
            )

        # Drop all other traffic by default
        match = parser.OFPMatch()

        self.add_flow(
            datapath,
            0,
            match,
            []
        )

        self.logger.info("Default network rules installed")

    def add_drop_rule(self, datapath, src, dst):
        parser = datapath.ofproto_parser

        match = parser.OFPMatch(
            eth_type=0x0800,
            ipv4_src=src,
            ipv4_dst=dst
        )

        self.add_flow(
            datapath,
            200,
            match,
            []
        )

        with self.lock:
            self.dynamic_drops.add((src, dst))

        self.logger.info(
            "DROP rule installed: %s -> %s",
            src,
            dst
        )

    def remove_drop_rule(self, datapath, src, dst):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        match = parser.OFPMatch(
            eth_type=0x0800,
            ipv4_src=src,
            ipv4_dst=dst
        )

        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            command=ofproto.OFPFC_DELETE_STRICT,
            priority=200,
            out_port=ofproto.OFPP_ANY,
            out_group=ofproto.OFPG_ANY,
            match=match
        )

        datapath.send_msg(flow_mod)

        with self.lock:
            self.dynamic_drops.discard((src, dst))

        self.logger.info(
            "DROP rule removed: %s -> %s",
            src,
            dst
        )

    # ------------------------------------------------------- socket server
    def socket_server(self):
        if self.tcp:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.tcp["host"], int(self.tcp["port"])))
            where = "%s:%s" % (self.tcp["host"], self.tcp["port"])
        else:
            # Remove an old socket file if one exists
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(self.socket_path)
            where = self.socket_path

        server.listen(5)

        self.logger.info("Controller socket listening at %s", where)

        while True:
            conn, _ = server.accept()

            try:
                command = conn.recv(1024).decode(errors="replace").strip()
                response = self.process_command(command)
                conn.sendall((response + "\n").encode())

            except Exception as e:
                self.logger.error("Socket error: %s", e)
                try:
                    conn.sendall(("ERR " + str(e) + "\n").encode())
                except OSError:
                    pass

            finally:
                conn.close()

    def process_command(self, command):
        parts = command.split()

        if not parts:
            return "ERR empty command"

        action = parts[0].upper()

        if action == "PING" and len(parts) == 1:
            return "OK " + self.boot_id

        if action == "CLEAR" and len(parts) == 1:
            with self.lock:
                datapaths = list(self.datapaths.values())
                drops = sorted(self.dynamic_drops)
            for datapath in datapaths:
                for src, dst in drops:
                    self.remove_drop_rule(datapath, src, dst)
            with self.lock:
                self.dynamic_drops.clear()
            self.logger.info("All dynamic drop rules cleared")
            return "OK all drops cleared"

        if len(parts) != 3:
            return "ERR invalid command format"

        action, src, dst = parts[0].upper(), parts[1], parts[2]

        if action == "DROP":
            with self.lock:
                self.dynamic_drops.add((src, dst))
                datapaths = list(self.datapaths.values())
            for datapath in datapaths:
                self.add_drop_rule(datapath, src, dst)

            return "OK DROP installed"

        elif action == "ALLOW":
            with self.lock:
                self.dynamic_drops.discard((src, dst))
                datapaths = list(self.datapaths.values())
            for datapath in datapaths:
                self.remove_drop_rule(datapath, src, dst)

            return "OK DROP removed"

        else:
            return "ERR unknown command"
