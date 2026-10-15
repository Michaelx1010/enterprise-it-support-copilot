# VPN access

## Connection failures

Use Northstar Connect on a managed laptop to reach internal services from home. First confirm that a public website loads without the VPN. If it does not, follow the Wi-Fi connection procedure. Select the Corporate gateway and reconnect once. Record the error code and time if the tunnel still fails. Do not disable endpoint protection or install a personal VPN client. Escalate persistent gateway errors to Network Support with the client version and error code.

## Authentication failures

The VPN uses the same company password and MFA as the identity portal. If the password was recently changed, remove the saved credential from Northstar Connect and sign in again. A missing or replaced authenticator belongs to the MFA recovery process, not a VPN client reinstall. If multiple applications reject the same credentials, follow the account-lockout checks. Never approve an unexpected MFA request.

## Connected but resources unavailable

When the VPN shows Connected but internal sites cannot be reached, check the gateway is Corporate and capture the affected internal hostname. Disconnect and reconnect once to refresh the tunnel routes. If internal sites work but one shared folder reports Access denied, request folder permission from its owner; a working tunnel does not grant access rights. Send widespread internal-hostname failures to Network Support. Do not change DNS servers manually.
