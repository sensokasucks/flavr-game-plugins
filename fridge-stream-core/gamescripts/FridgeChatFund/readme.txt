FridgeChatFund — OpenTTD Game Script for Fridge Stream Core
===========================================================

What it does
------------
Receives JSON from the Admin Port (sent by Stream Core on !invest)
and credits that company with GSCompany.ChangeBankBalance.

Vanilla / JGR console cannot grant cash. This script is the in-game half
of chat funding. Without it, Core still deducts points, announces in
server chat, and queues the injection until the script is loaded.

Install
-------
1. Copy the FridgeChatFund folder to:
     <OpenTTD documents>/game/FridgeChatFund/
   or use the in-game AI/Game Script settings after placing it there.
2. New game / scenario: set Game Script to FridgeChatFund.
3. Server: set network.admin_password and server_admin_port (3977).
4. Stream Core config:
     openttd.enabled: true
     openttd.admin_password: same password
     openttd.use_gamescript: true

Packet
------
{"action":"invest","company":2,"pounds":50000,"from":"Sensoka","points":50}

Notes
-----
- Does not restore or use company shares.
- Chat Fund companies (per-viewer AI IPOs) are a later module.
- Safe to run on JGRPP and vanilla 14+.
