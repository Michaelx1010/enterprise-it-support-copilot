"""Explicit admin commands and six developer lookups. No agent dispatch."""

import argparse
import json
from pathlib import Path
import sys

from pydantic import ValidationError

from app.operations.db import OperationalDB, OperationalDataError, admin_url, initialize, provision_reader
from app.operations.seed import seed
from app.operations import schemas as s, tools


def add_commands(commands: argparse._SubParsersAction) -> None:
    parser = commands.add_parser('ops', help='Synthetic operational data and read-only investigation.')
    sub = parser.add_subparsers(dest='ops_command', required=True)
    sub.add_parser('init', help='Admin: create isolated operational schema; never resets data.')
    sub.add_parser('seed', help='Admin: insert deterministic fictional records; refuse conflicts.')
    provision = sub.add_parser('provision-reader', help='Admin: create restricted login and a new ignored local env file.')
    provision.add_argument('--env-file', type=Path, default=Path('.env.ops'))
    for command in ('account', 'devices', 'tickets'):
        p = sub.add_parser(command)
        p.add_argument('employee_id')
        if command == 'tickets':
            p.add_argument('--limit', type=int, default=10)
            p.add_argument('--since', help='Inclusive ISO-8601 timestamp including timezone.')
    sub.add_parser('device').add_argument('device_id')
    entitlement = sub.add_parser('entitlement')
    entitlement.add_argument('employee_id')
    entitlement.add_argument('software_id')
    incidents = sub.add_parser('incidents')
    incidents.add_argument('--service-id')
    incidents.add_argument('--limit', type=int, default=20)


def run(args: argparse.Namespace) -> int:
    try:
        if args.ops_command == 'init':
            initialize(admin_url())
            output = {'status': 'ok', 'operation': 'initialized_ops'}
        elif args.ops_command == 'seed':
            output = {'status': 'ok', 'inserted': seed(admin_url())}
        elif args.ops_command == 'provision-reader':
            provision_reader(admin_url(), args.env_file)
            output = {'status': 'ok', 'operation': 'reader_provisioned', 'env_file': str(args.env_file)}
        else:
            if args.ops_command == 'account':
                request = s.EmployeeInput(employee_id=args.employee_id)
                function = tools.get_employee_account_status
            elif args.ops_command == 'devices':
                request = s.EmployeeInput(employee_id=args.employee_id)
                function = tools.get_employee_devices
            elif args.ops_command == 'device':
                request = s.DeviceInput(device_id=args.device_id)
                function = tools.get_device_details
            elif args.ops_command == 'entitlement':
                request = s.EntitlementInput(employee_id=args.employee_id, software_id=args.software_id)
                function = tools.check_software_entitlement
            elif args.ops_command == 'tickets':
                request = s.RecentTicketsInput(employee_id=args.employee_id, limit=args.limit, since=args.since)
                function = tools.get_recent_support_tickets
            else:
                request = s.ActiveIncidentsInput(service_id=args.service_id, limit=args.limit)
                function = tools.get_active_service_incidents
            output = function(request, db=OperationalDB.from_environment()).model_dump(mode='json')
        print(json.dumps(output, indent=2))
    except ValidationError:
        print(json.dumps({'error': {'code': 'invalid_input', 'message': 'Invalid operational tool parameters.'}}), file=sys.stderr)
        return 2
    except OperationalDataError as exc:
        # Messages are fixed in this package; never emit raw exceptions or input values.
        print(json.dumps({'error': {'code': exc.code, 'message': str(exc)}}), file=sys.stderr)
        return 1
    return 0
