# SD-WAN Packet Duplication & De-Duplication for Zero-Loss Voice & Video

## Summary
In mission-critical enterprise environments, real-time communication protocols such as **SIP, RTP (VoIP), and interactive video conferencing (Zoom, Microsoft Teams)** cannot tolerate packet drops. While traditional SD-WAN SLA steering shifts traffic after detecting link degradation, voice calls still suffer audible clicks, robotic stutter, or dropped calls during the detection and failover convergence window.

To achieve **zero-loss resilience**, FortiOS provides **Packet Duplication and De-Duplication**:
1. **Sender Engine (Branch 1):** Intercepts outbound voice/video flows on LAN ingress and clones each packet in real time. Identical frames are transmitted simultaneously across both **MPLS-VPN** (**port2**) and **BB-VPN** (**port3**) overlay members within the `VPN-ZONE`.
2. **Receiver Engine (HQ Hub):** The receiving FortiGate buffers incoming frames across both tunnels. The first arriving packet is forwarded immediately to the destination host (**port1**), while the redundant duplicate is discarded at the kernel boundary.
3. **The Proof:** By injecting **15% to 18% packet loss on MPLS** and **29% to 33% packet loss on Broadband** using an inline Linux Degradation Device (`tc netem`), this project demonstrates that while an un-duplicated stream suffered **17% packet loss**, an active duplicated stream achieved **0% packet loss** with continuous payload delivery.

**Live Execution showing duplication vs no duplication**

https://github.com/user-attachments/assets/c31203d5-b45f-4fdc-b301-3a1984fd6e9a

---

## Lab Architecture & Test Topology

![sd-wan](screenshots/duplication-draw-io.png)

![sd-wan](screenshots/topology.png)

### Addressing & SD-WAN Overlay 
| Device | Role | Physical Interfaces | Overlay Interfaces | SD-WAN Zone | Subnet |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Fortinet-Branch-1** | Duplication Sender | port2 (MPLS): 10.0.1.6/30<br>port3 (BB): 10.0.2.6/30<br>port1 (LAN): 10.20.20.1/24 | Member 3: MPLS-VPN<br>Member 4: BB-VPN | VPN-ZONE | BRANCH-1-LAN (10.20.20.0/24) |
| **Fortinet-HQ** | De-Duplication Receiver | port2 (MPLS): 10.0.1.2/30<br>port3 (BB): 10.0.2.2/30<br>port1 (LAN): 10.10.10.1/24 | Member 3: MPLS-VPN<br>Member 4: BB-VPN | VPN-ZONE | HQ-LAN (10.10.10.0/24) |
| **Branch-1-PC** | Test Client | eth0 | — | — | 10.20.20.10/24 |
| **HQ-Server** | Target PBX / Core Server | eth0 | — | — | 10.10.10.10/24 |
| **Network Degradation Node** | Impairment Appliance | eth0 (WAN), eth1 (LAN) | Bridged inline with Linux kernel tc netem | — | Inline bridge on provider links |

---

## Configuration & Architecture Design

### 1. Sender Duplication Rule on Fortinet-Branch-1
On Branch 1, `duplication-max-num` is set to 2, instructing the SD-WAN engine to clone matching traffic across up to two active overlay members in the destination zone (`VPN-ZONE`). Setting `packet-duplication force` ensures that every single frame matching the address tuple is cloned regardless of SLA status:

```fortios
config system sdwan
    set duplication-max-num 2
    config duplication
        edit 1
            set srcaddr "BRANCH-1-LAN"
            set dstaddr "HQ-LAN"
            set srcintf "port1"
            set dstintf "VPN-ZONE"
            set service "ALL"
            set packet-duplication force
            set packet-de-duplication enable
        next
    end
end
```

![sd-wan](screenshots/config-duplication-show-branch.png)


### 2. SD-WAN Member Mappings on Branch-1
Both route-based IPsec tunnels are consolidated under the logical SD-WAN zone `VPN-ZONE`:

```fortios
config system sdwan
    config members
        edit 3
            set interface "MPLS-VPN"
            set zone "VPN-ZONE"
        next
        edit 4
            set interface "BB-VPN"
            set zone "VPN-ZONE"
        next
    end
end
```
![sd-wan](screenshots/config-members-show-zone-branch.png)

### 3. Receiver De-Duplication Rule on Fortinet-HQ
On HQ, packet de-duplication is enabled for ingress traffic arriving on `VPN-ZONE` destined for the internal LAN (`port1`). The kernel maintains an ephemeral sliding window to track packet sequence numbers and drops duplicate arrivals:

```fortios
config system sdwan
    config duplication
        edit 1
            set srcaddr "Branch1-LAN-Subnet"
            set dstaddr "HQ-LAN"
            set srcintf "VPN-ZONE"
            set dstintf "port1"
            set service "ALL"
            set packet-de-duplication enable
        next
    end
end
```
![sd-wan](screenshots/config-duplication-show-hq.png)

---

## Verification & Impairment Testing Lifecycle

### Phase 1: Dual-Egress Wire Sniffing on Branch 1 (Sender Proof)
To prove that Branch 1 actively clones traffic across both overlays, a live sniffer was executed on `Fortinet-Branch-1` while `Branch-1-PC` pinged `HQ-Server` (`10.10.10.10`):

```text
FortiGate-VM64-KVM # diagnose sniffer packet any "host 10.10.10.10 and icmp" 4 0 l
interfaces=[any]
filters=[host 10.10.10.10 and icmp]
2026-11-02 01:16:13.158548 port1 in 10.20.20.10 -> 10.10.10.10: icmp: echo request
2026-11-02 01:16:13.158662 BB-VPN out 10.20.20.10 -> 10.10.10.10: icmp: echo request   <-- Copy 1 (Broadband)
2026-11-02 01:16:13.158895 MPLS-VPN out 10.20.20.10 -> 10.10.10.10: icmp: echo request <-- Copy 2 (MPLS)
```
* For every single packet entering port1 from the client, two identical echo requests egress simultaneously out of BB-VPN and MPLS-VPN.

![sd-wan](screenshots/diagnose-sniffer-packet-branch-duplication-enabled.png)

---

### Phase 2: Kernel De-Duplication Verification on HQ (Receiver Proof)
On `Fortinet-HQ`, the sniffer captures both tunnel arrivals while verifying that the destination host on LAN (`port1`) receives only a single copy:

```text
FortiGate-VM64-KVM # diagnose sniffer packet any "host 10.10.10.10 and icmp" 4 0 l
interfaces=[any]
filters=[host 10.10.10.10 and icmp]
2026-11-02 01:14:37.577259 BB-VPN in 10.20.20.10 -> 10.10.10.10: icmp: echo request   <-- Arrives via Broadband
2026-11-02 01:14:37.577295 port1 out 10.20.20.10 -> 10.10.10.10: icmp: echo request    <-- Forwarded to server
2026-11-02 01:14:37.580830 MPLS-VPN in 10.20.20.10 -> 10.10.10.10: icmp: echo request  <-- Arrives via MPLS
                                                                                         <-- SECOND COPY DISCARDED
```
* **Key Evidence:** Notice that after `MPLS-VPN in` arrives, there is **no second port1 out**. The HQ FortiGate de-duplicated the packet in the kernel, protecting the target server from receiving duplicate frames.

![sd-wan](screenshots/diagnose-sniffer-de-duplication.png)

---

### Typical Forwarding Behavior Without Packet Duplication (Baseline)

To demonstrate why packet duplication is necessary for loss-sensitive traffic, the duplication rule was temporarily removed from Branch 1 (`delete 1`). Traffic between Branch 1 (`10.20.20.10`) and HQ (`10.10.10.10`) was captured under standard SD-WAN zone forwarding.

![sd-wan](screenshots/deleting-duplication-rule.png)

#### 1. Single-Path Egress Wire Telemetry
In typical SD-WAN operation, even when multiple active overlay tunnels belong to the same zone (`VPN-ZONE`), the FortiGate hash and steering engines pin each individual flow to **a single egress member**:

```text
FortiGate-VM64-KVM # diagnose sniffer packet any "host 10.10.10.10 and icmp" 4 0 l
Using Original Sniffing Mode
interfaces=[any]
filters=[host 10.10.10.10 and icmp]
2026-11-02 01:38:12.756682 port1 in 10.20.20.10 -> 10.10.10.10: icmp: echo request
2026-11-02 01:38:12.756783 MPLS-VPN out 10.20.20.10 -> 10.10.10.10: icmp: echo request   <-- Single egress path
2026-11-02 01:38:12.776746 MPLS-VPN in 10.10.10.10 -> 10.20.20.10: icmp: echo reply
2026-11-02 01:38:12.776786 port1 out 10.10.10.10 -> 10.20.20.10: icmp: echo reply
2026-11-02 01:38:13.757772 port1 in 10.20.20.10 -> 10.10.10.10: icmp: echo request
2026-11-02 01:38:13.757798 MPLS-VPN out 10.20.20.10 -> 10.10.10.10: icmp: echo request   <-- Single egress path
2026-11-02 01:38:13.769022 MPLS-VPN in 10.10.10.10 -> 10.20.20.10: icmp: echo reply
2026-11-02 01:38:13.769035 port1 out 10.10.10.10 -> 10.20.20.10: icmp: echo reply
^C
32 packets received by filter
0 packets dropped by kernel
```
![sd-wan](screenshots/diagnose-sniffer-packet-no-duplication.png)

#### 2. Key Observations & Comparison:

| Parameter | Typical Standard Behavior (No Duplication) | Active Packet Duplication Behavior |
| :--- | :--- | :--- |
| **Ingress Packets (LAN port1)** | 1 Echo Request from client | 1 Echo Request from client |
| **Egress Packets (WAN Tunnels)** | **1 frame total** (pinned strictly to MPLS-VPN) | **2 identical frames** (cloned simultaneously out MPLS-VPN and BB-VPN) |
| **Secondary Tunnel State** | BB-VPN sits completely idle for this session flow | BB-VPN actively transmits the parallel redundant stream |
| **Impact of 15% Link Degradation** | Dropped frames are permanently lost, causing **17% packet loss** on the end client | Redundant frames fill in the drops, delivering **0% packet loss** to the destination |

#### 3. Why This Proves the Value of Packet Duplication
* **The Vulnerability:** Under typical SD-WAN behavior, if an underlay circuit experiences transient packet loss or intermittent drops, the application bears the full brunt of the packet loss until SLA probes detect the failure and trigger a path switch.
* **The Resolution:** As proven by the contrast in sniffer captures, enabling packet duplication eliminates this vulnerability entirely by converting the fabric from reactive failover to proactive dual-path transmission.

### Phase 3: Negative Control — 15% MPLS Loss Without Duplication
To establish a baseline failure mode, the duplication rule was deleted from Branch 1 (`delete 1`). SD-WAN Service Rule 1 was set to manual mode targeting `MPLS-VPN`, and 15% packet loss was injected using the Linux degradation device:

```bash
localhost:~# sudo tc qdisc add dev eth0 root netem loss 15%
```
![sd-wan](screenshots/mpls-test-intentional-packet-loss.png)

![sd-wan](screenshots/mpls-test-topology.png)

1. **SD-WAN Health-Check Reaction:**
   ```text
   FortiGate-VM64-KVM # diagnose sys sdwan health-check
   Seq(3 MPLS-VPN): state(alive), packet-loss(19.000%) latency(18.374), jitter(2.184) sla_map=0x0
   Seq(4 BB-VPN): state(alive), packet-loss(0.000%) latency(19.057), jitter(1.394) sla_map=0x1
   ```
![sd-wan](screenshots/mpls-test-health-check.png)

2. **Client-Side Degradation:**
   With duplication disabled, traffic was pinned to the degraded MPLS link. Ping statistics on `Branch-1-PC` confirmed severe packet drops:
   ```bash
   localhost:~# ping 10.10.10.10
   --- 10.10.10.10 ping statistics ---
   39 packets transmitted, 32 packets received, 17% packet loss
   round-trip min/avg/max = 16.532/22.896/28.474 ms
   ```
   *17% of packets were permanently lost, demonstrating the destructive impact on voice sessions without duplication.*

![sd-wan](screenshots/mpls-test-17-percent-packet-loss.png)

---

### Phase 4: Active Duplication under 15%–19% MPLS Loss (The Zero-Loss Proof)
With 15% packet loss active on MPLS, the duplication rule was re-enabled on Branch 1 and HQ:

```bash
localhost:~# ping 10.10.10.10
--- 10.10.10.10 ping statistics ---
20 packets transmitted, 20 packets received, 0% packet loss
round-trip min/avg/max = 14.035/21.175/28.570 ms
```
* **Result:** **0% packet loss**. Every frame dropped by `tc netem` on the MPLS underlay was seamlessly compensated for by the redundant copy arriving across Broadband.

![sd-wan](screenshots/mpls-test-0-percent-packet-loss.png)

---

### Phase 5: Active Duplication under ISP (Broadband) Impairment
The Linux degradation device was moved inline to the Broadband path, injecting 15% loss:

![sd-wan](screenshots/broadband-test-intentional-packet-loss.png)

![sd-wan](screenshots/broadband-test-topology.png)

1. **SD-WAN Health Check Telemetry:**
   ```text
   FortiGate-VM64-KVM # diagnose sys sdwan health-check
   Seq(3 MPLS-VPN): state(alive), packet-loss(0.000%) latency(19.533), jitter(1.330) sla_map=0x1
   Seq(4 BB-VPN): state(alive), packet-loss(33.000%) latency(20.675), jitter(1.419) sla_map=0x0
   ```
   
![sd-wan](screenshots/broadband-test-health-check.png)
   
2. **Client-Side Verification:**
   ```bash
   localhost:~# ping 10.10.10.10
   --- 10.10.10.10 ping statistics ---
   15 packets transmitted, 15 packets received, 0% packet loss
   ```
   *Despite 33% packet loss detected on BB-VPN, the client maintained complete data plane continuity with 0% loss.*

![sd-wan](screenshots/broadband-test-0-percent-packet-loss.png)

---

## Key Evidence Index (Curated Proof)

| Category / Phase | Key Artifact (`screenshots/`) | Purpose & Technical Verification |
| :--- | :--- | :--- |
| **Topology** | `topology.png` | Network topology diagram showing multi-site underlays, overlay tunnels, and inline degradation device. |
| **Configuration** | `config-duplication-show-branch.png` | Branch 1 sender duplication rule cloning traffic across VPN-ZONE with force enabled. |
| **Configuration** | `config-duplication-show-hq.png` | HQ receiver de-duplication rule buffering incoming frames and discarding redundant arrivals. |
| **Wire Proof (Sender)** | `diagnose-sniffer-packet-branch-duplication-enabled.png` | **Dual Egress Proof:** Sniffer on Branch 1 proving simultaneous echo requests out MPLS-VPN and BB-VPN for every single LAN ingress packet. |
| **Wire Proof (Receiver)** | `diagnose-sniffer-de-duplication.png` | **Smoking Gun:** Sniffer on HQ showing two tunnel arrivals but strictly one echo request forwarded to the LAN server. |
| **Negative Control** | `diagnose-sniffer-packet-no-dupliaction.png` | **Standard Behavior:** Sniffer proving that without duplication, traffic pins to a single tunnel interface while the backup sits idle. |
| **Negative Control** | `mpls-test-17-percent-packet-loss.png` | **Failure Baseline:** Client ping showing 17% packet loss when duplication is off and MPLS is impaired. |
| **Impairment Injection**| `mpls-test-intentional-packet-loss.png` | Linux terminal output applying `sudo tc qdisc add dev eth0 root netem loss 15%` on the degradation appliance. |
| **SLA Detection** | `mpls-test-health-check.png` | SD-WAN health check actively detecting 19% packet loss on MPLS-VPN (disqualifying SLA). |
| **The "Money Shot"** | `mpls-test-0-percent-packet-loss.png` | **Zero-Loss Proof:** Client ping recovering to **0% packet loss** across the exact same impaired link once duplication is enabled. |
| **Broadband Stress** | `broadband-test-health-check.png` | Health check logging severe packet loss (29%–33%) when the Broadband overlay is degraded. |
| **Broadband Stress** | `broadband-test-0-percent-packet-loss.png` | Client ping confirming **0% packet loss** maintained even under heavy Broadband degradation. |
| **Live Video Proof** | `sd-wan-duplication-test-2026-11-02_05.48.05.mp4` | Screen recording capturing live packet cloning, degradation injection, and zero-loss ping recovery. |

---

## Business Value Delivered
* **Guaranteed 0% Loss for Real-Time Voice/Video:** Eliminates the transitional audio dropouts, robotic voice distortions, and video freezes that occur during standard SLA failover reconvergence windows.
* **Proactive Hitless Failover:** Rather than reacting *after* a link drops below an SLA threshold, duplicate transmission ensures uninterrupted session continuity even if an underlay suffers sudden, severe packet degradation.
* **Zero Host Overhead:** Operates entirely within the FortiGate network processors and kernel boundary; endpoint IP phones, UC clients (Teams/Zoom), and PBX servers require no custom software or modification.

---

[Back to Fortinet Module Overview](../README.md) · [Next Module: Cisco Catalyst SD-WAN (Viptela)](../../02-Cisco-Catalyst-SDWAN/)
