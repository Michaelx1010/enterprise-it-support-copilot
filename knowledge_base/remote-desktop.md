# Remote desktop access

## Prerequisites and authorization

Remote desktop to a company workstation requires manager approval, membership in the Remote Access group, and an enabled target workstation. Off-site users must first establish the Corporate VPN tunnel. IT enables remote access after approval; users must not open router ports or expose their workstation to the internet. Submit the target asset name and business justification with the request.

## Target workstation unreachable

If the VPN is connected and internal websites work but one workstation cannot be reached, confirm its asset name and ask the office contact whether it is powered on. Report the target asset, error text, and last successful connection to Endpoint Support. Do not reboot another employee's workstation. If all internal destinations fail, use VPN connected-but-resources-unavailable checks instead.

## Session drops and poor responsiveness

Compare normal browsing and VPN stability with the time of each session freeze. If only remote desktop is affected, record the session error, target asset, and whether the remote application or the entire desktop freezes. Reconnect once. Save work frequently and do not forcibly sign out another session. Escalate repeated drops with timestamps to Endpoint Support.
