import argparse
import json
import sys

from pm_agent_api.repositories import create_state_repository
from pm_agent_api.services.auth_service import AuthService, DuplicateUserError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap the first admin user into persisted PM Agent state.")
    parser.add_argument("--email", required=True, help="Admin email address")
    parser.add_argument("--password", required=True, help="Admin password")
    parser.add_argument("--display-name", default=None, help="Optional admin display name")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    repository = create_state_repository()
    auth_service = AuthService(repository)

    try:
        user = auth_service.bootstrap_admin(args.email, args.password, args.display_name)
    except (DuplicateUserError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1

    print(json.dumps({"id": user["id"], "email": user["email"], "role": user["role"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
