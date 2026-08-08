import ast
import re
import shlex
from pathlib import Path

import yaml


PINNED_GEMINI_SECRET = (
    "--update-secrets=GEMINI_API_KEY=sumai-gemini-api-key:2"
)
EVIDENCE_FILE = "/workspace/candidate-evidence.json"
EVIDENCE_DESTINATION = (
    "gs://$PROJECT_ID-sumai-release-evidence/candidates/"
    "$COMMIT_SHA/$BUILD_ID.json"
)
EXPECTED_EVIDENCE_WRITE = (
    'Path("/workspace/candidate-evidence.json").write_text('
    'json.dumps(evidence, sort_keys=True) + "\\n", encoding="utf-8")'
)
DIGEST_PATTERN = "^sha256:[0-9a-f]{64}$"
EXPECTED_EVIDENCE_EXPRESSIONS = {
    "schema_version": "1",
    "source_commit": 'os.environ["COMMIT_SHA"]',
    "build_id": 'os.environ["BUILD_ID"]',
    "project_id": 'os.environ["PROJECT_ID"]',
    "region": 'os.environ["REGION"]',
    "agent_digest": 'values["agent_digest"]',
    "agent_revision": 'values["agent_revision"]',
    "agent_url": 'values["agent_url"]',
    "agent_service_account": 'values["agent_service_account"]',
    "agent_resource_version_before": (
        'values["agent_resource_version_before"]'
    ),
    "agent_resource_version_after": 'values["agent_resource_version_after"]',
    "agent_production_before": 'values["agent_production_before"]',
    "web_digest": 'values["web_digest"]',
    "web_revision": 'values["web_revision"]',
    "web_url": 'values["web_url"]',
    "web_service_account": 'values["web_service_account"]',
    "web_resource_version_before": 'values["web_resource_version_before"]',
    "web_resource_version_after": 'values["web_resource_version_after"]',
    "web_production_before": 'values["web_production_before"]',
    "production_traffic_changed": "False",
}


def step_command_text(step_id: str, step: dict) -> str:
    entrypoint = step.get("entrypoint")
    if entrypoint is not None:
        assert isinstance(entrypoint, str), f"{step_id} entrypoint must be a string"

    script = step.get("script")
    if script is not None:
        assert isinstance(script, str), f"{step_id} script must be a string"

    args = step.get("args", [])
    assert isinstance(args, list), f"{step_id} command args must be a list"
    assert all(isinstance(arg, str) for arg in args), (
        f"{step_id} command args must all be strings"
    )

    if script is not None:
        prefix = f"{entrypoint}\n" if entrypoint else ""
        return f"{prefix}{script}".strip()
    if args and all("\n" not in arg for arg in args):
        return " ".join(
            [part for part in (entrypoint, *args) if part]
        ).strip()
    return "\n".join(arg.strip() for arg in args if arg.strip())


def shell_command_segments(command_text: str) -> list[str]:
    logical_text = re.sub(r"\\[ \t]*\n", " ", command_text)
    segments = []
    for line in logical_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        segments.extend(
            segment.strip()
            for segment in re.split(r"\s*(?:&&|\|\||;)\s*", line)
            if segment.strip()
        )
    return segments


def validate_traffic_commands(command_steps: dict[str, str]) -> None:
    deploy_steps = {"deploy-agent-candidate", "deploy-web-candidate"}
    service_update_steps = {"deploy-agent-candidate"}
    deploy_pattern = re.compile(r"\bgcloud\s+run\s+deploy(?=\s|$)", re.IGNORECASE)
    update_pattern = re.compile(
        r"\bgcloud\s+run\s+services\s+update(?=\s|$)",
        re.IGNORECASE,
    )
    replace_pattern = re.compile(
        r"\bgcloud\s+run\s+services\s+replace(?=\s|$)",
        re.IGNORECASE,
    )
    update_traffic_pattern = re.compile(
        r"\bgcloud\s+run\s+services\s+update-traffic(?=\s|$)",
        re.IGNORECASE,
    )
    no_traffic_pattern = re.compile(r"(?<![\w-])--no-traffic(?![\w-])")

    for step_id, command_text in command_steps.items():
        for segment in shell_command_segments(command_text):
            assert replace_pattern.search(segment) is None, (
                f"{step_id} contains forbidden gcloud run services replace"
            )
            assert update_traffic_pattern.search(segment) is None, (
                f"{step_id} contains forbidden gcloud run services update-traffic"
            )
            assert not re.search(
                r"(?<![\w-])update-traffic(?![\w-])",
                segment,
                re.IGNORECASE,
            ), f"{step_id} contains forbidden update-traffic command text"
            assert "--to-revisions" not in segment, (
                f"{step_id} contains forbidden --to-revisions traffic assignment"
            )

            if deploy_pattern.search(segment):
                assert step_id in deploy_steps, (
                    f"{step_id} contains gcloud run deploy outside candidate deploy steps"
                )
                assert no_traffic_pattern.search(segment), (
                    f"{step_id} gcloud run deploy must include --no-traffic"
                )

            if update_pattern.search(segment):
                assert step_id in service_update_steps, (
                    f"{step_id} contains gcloud run services update outside "
                    "deploy-agent-candidate"
                )
                assert no_traffic_pattern.search(segment), (
                    f"{step_id} gcloud run services update must include --no-traffic"
                )


def normalized_shell_contract(command_text: str) -> str:
    without_continuations = re.sub(r"\\[ \t]*\n", " ", command_text)
    return re.sub(r"\s+", " ", without_continuations).replace("$$", "$").strip()


def validate_production_service_account_preconditions(
    command_steps: dict[str, str],
) -> None:
    step_id = "deploy-agent-candidate"
    assert step_id in command_steps, f"missing Cloud Build step: {step_id}"
    command_text = command_steps[step_id]
    normalized = normalized_shell_contract(command_text)
    mutation = re.search(
        r"\bgcloud\s+run\s+(?:deploy|services\s+update)(?=\s|$)",
        normalized,
        re.IGNORECASE,
    )
    assert mutation is not None, (
        f"{step_id} must contain a candidate or migration mutation"
    )

    specifications = {
        "agent": {
            "production_revision": "agent_production_before",
            "production_service_account": "agent_production_service_account",
            "service_account_substitution": "_AGENT_SERVICE_ACCOUNT",
        },
        "web": {
            "production_revision": "web_production_before",
            "production_service_account": "web_production_service_account",
            "service_account_substitution": "_WEB_SERVICE_ACCOUNT",
        },
    }
    for component, specification in specifications.items():
        production_revision = specification["production_revision"]
        production_service_account = specification["production_service_account"]
        service_account_substitution = specification[
            "service_account_substitution"
        ]
        production_assignment_pattern = re.compile(
            rf"(?m)^[ \t]*{re.escape(production_revision)}\s*=",
        )
        production_assignments = list(
            production_assignment_pattern.finditer(command_text)
        )
        assert len(production_assignments) == 1, (
            f"{step_id} must resolve the serving {component} revision exactly once"
        )
        service_account_assignment_pattern = re.compile(
            rf"(?m)^[ \t]*{re.escape(production_service_account)}\s*=",
        )
        service_account_assignments = list(
            service_account_assignment_pattern.finditer(command_text)
        )
        assert len(service_account_assignments) == 1, (
            f"{step_id} must assign the serving {component} service account "
            "exactly once"
        )
        assert (
            production_assignments[0].start()
            < service_account_assignments[0].start()
        ), (
            f"{step_id} must resolve the serving {component} revision before "
            "describing its service account"
        )
        assert not re.search(
            rf"(?ms)^[ \t]*{re.escape(production_service_account)}\s*=\s*"
            rf"[\"']?\$\$?\(\s*gcloud\s+run\s+services\s+describe\b",
            command_text,
            re.IGNORECASE,
        ), (
            f"{step_id} must not derive the serving {component} service account "
            "from the mutable service template"
        )

        fragments = {
            "exact serving-revision describe": (
                f'{production_service_account}="$(gcloud run revisions describe '
                f'"${production_revision}" --project="$PROJECT_ID" '
                '--region="${_REGION}" '
                "--format='value(spec.serviceAccountName)')\""
            ),
            "nonempty check": f'test -n "${production_service_account}"',
            "caller identity binding": (
                f'test "${production_service_account}" = '
                f'"${{{service_account_substitution}}}"'
            ),
        }
        positions = []
        for contract_name, fragment in fragments.items():
            assert normalized.count(fragment) == 1, (
                f"{step_id} missing ordered {component} {contract_name}"
            )
            positions.append(normalized.index(fragment))
        assert positions == sorted(positions), (
            f"{step_id} must resolve, validate, then bind the serving "
            f"{component} service account"
        )
        assert all(position < mutation.start() for position in positions), (
            f"{step_id} must bind the serving {component} service account "
            "before any Cloud Run mutation"
        )


def validate_digest_provenance(command_steps: dict[str, str]) -> None:
    specifications = {
        "agent": {
            "push_step": "push-agent",
            "deploy_step": "deploy-agent-candidate",
            "reference": "agent_ref",
            "digest": "agent_digest",
            "push_log": "/workspace/sumai-agent-push.log",
            "digest_file": "/workspace/sumai-agent.digest",
        },
        "web": {
            "push_step": "push-web",
            "deploy_step": "deploy-web-candidate",
            "reference": "web_ref",
            "digest": "web_digest",
            "push_log": "/workspace/sumai-web-push.log",
            "digest_file": "/workspace/sumai-web.digest",
        },
    }

    for component, specification in specifications.items():
        push_step = specification["push_step"]
        deploy_step = specification["deploy_step"]
        assert push_step in command_steps, f"missing Cloud Build step: {push_step}"
        assert deploy_step in command_steps, f"missing Cloud Build step: {deploy_step}"

        push_command = normalized_shell_contract(command_steps[push_step])
        reference = specification["reference"]
        push_log = specification["push_log"]
        digest_file = specification["digest_file"]
        push_contracts = {
            "pushed-image output capture": (
                f'docker push "${reference}" | tee {push_log}'
            ),
            "pushed-output digest extraction": (
                f"awk '/digest: sha256:/{{print $3}}' {push_log} | "
                f"tail -1 > {digest_file}"
            ),
            "exact SHA-256 digest validation": (
                f"grep -Eq '{DIGEST_PATTERN}' {digest_file}"
            ),
        }
        push_positions = []
        for contract_name, required_fragment in push_contracts.items():
            assert push_command.count(required_fragment) == 1, (
                f"{push_step} missing {component} {contract_name}"
            )
            push_positions.append(push_command.index(required_fragment))
        assert push_positions == sorted(push_positions), (
            f"{push_step} must capture, extract, then validate the {component} digest"
        )

        deploy_command = normalized_shell_contract(command_steps[deploy_step])
        digest = specification["digest"]
        assignment_pattern = re.compile(
            rf"(?m)(?:^[ \t]*|[;&|][ \t]*)"
            rf"(?:(?:export|readonly|local)\s+|declare(?:\s+-\w+)?\s+)?"
            rf"{re.escape(digest)}\s*="
        )
        assignments = list(assignment_pattern.finditer(command_steps[deploy_step]))
        assert len(assignments) == 1, (
            f"{deploy_step} must assign {component} digest exactly once"
        )
        deploy_contracts = {
            "workspace digest read": (
                f'{digest}="$(cat {digest_file})"'
            ),
            "exact SHA-256 digest validation": (
                f"printf '%s' \"${digest}\" | grep -Eq '{DIGEST_PATTERN}'"
            ),
            "immutable digest image reference": (
                f'--image="${{{reference}%:*}}@${{{digest}}}"'
            ),
        }
        deploy_positions = []
        for contract_name, required_fragment in deploy_contracts.items():
            assert deploy_command.count(required_fragment) == 1, (
                f"{deploy_step} missing {component} {contract_name}"
            )
            deploy_positions.append(deploy_command.index(required_fragment))
        assert deploy_positions == sorted(deploy_positions), (
            f"{deploy_step} must read, validate, then deploy the {component} digest"
        )
        assert not re.search(
            rf"(?m)^[ \t]*(?:unset|read)\s+{re.escape(digest)}\b|"
            rf"\bprintf\s+-v\s+{re.escape(digest)}\b",
            command_steps[deploy_step],
        ), f"{deploy_step} must not alter the {component} digest after assignment"

        for step_id, command_text in command_steps.items():
            if step_id == push_step:
                expected_occurrences = 2
            elif step_id == deploy_step:
                expected_occurrences = 1
            else:
                expected_occurrences = 0
            assert command_text.count(digest_file) == expected_occurrences, (
                f"{step_id} has unexpected {component} workspace digest-file access"
            )


def parsed_secret_flag_tokens(step_id: str, command_text: str) -> list[str]:
    tokens = []
    for segment in shell_command_segments(command_text):
        if not re.search(r"--(?:set|update)-secrets", segment, re.IGNORECASE):
            continue
        try:
            lexer = shlex.shlex(segment, posix=True, punctuation_chars=";&|")
            lexer.whitespace_split = True
            lexer.commenters = "#"
            segment_tokens = list(lexer)
        except ValueError as error:
            raise AssertionError(
                f"{step_id} has an unparsable secret-binding command"
            ) from error
        for index, token in enumerate(segment_tokens):
            previous = segment_tokens[index - 1] if index else ""
            previous_is_secret_flag = previous.casefold() in {
                "--set-secrets",
                "--update-secrets",
            }
            if "gemini_api_key" in token.casefold() and (
                "secret" in token.casefold() or previous_is_secret_flag
            ):
                tokens.append(token)
    return tokens


def validate_exact_gemini_secret_binding(
    command_steps: dict[str, str],
) -> None:
    bindings = []
    for step_id, command_text in command_steps.items():
        bindings.extend(
            (step_id, token)
            for token in parsed_secret_flag_tokens(step_id, command_text)
        )
    assert len(bindings) == 1, (
        "Cloud Build must contain exactly one Gemini Secret Manager binding token"
    )
    binding_step, binding_token = bindings[0]
    assert binding_step == "deploy-agent-candidate", (
        "Gemini Secret Manager binding must belong to deploy-agent-candidate"
    )
    assert binding_token == PINNED_GEMINI_SECRET, (
        "deploy-agent-candidate must use the exact pinned Gemini secret token"
    )

    agent_deploy = extract_deploy_command(
        "deploy-agent-candidate",
        command_steps["deploy-agent-candidate"],
    )
    try:
        deploy_tokens = shlex.split(agent_deploy, comments=True, posix=True)
    except ValueError as error:
        raise AssertionError(
            "deploy-agent-candidate has an unparsable deploy command"
        ) from error
    assert deploy_tokens.count(PINNED_GEMINI_SECRET) == 1, (
        "deploy-agent-candidate deploy must own the one exact pinned secret token"
    )


def extract_deploy_command(step_id: str, command_text: str) -> str:
    lines = command_text.splitlines()
    matches = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.search(r"\bgcloud\s+run\s+deploy\b", line):
            command_lines = [line.strip()]
            while command_lines[-1].rstrip().endswith("\\"):
                index += 1
                assert index < len(lines), (
                    f"{step_id} has an unterminated gcloud run deploy command"
                )
                command_lines.append(lines[index].strip())
            matches.append(" ".join(command_lines).replace("\\", ""))
        index += 1
    assert len(matches) == 1, (
        f"{step_id} must contain exactly one gcloud run deploy command"
    )
    return re.sub(r"\s+", " ", matches[0]).strip()


def deploy_environment(step_id: str, deploy_command: str) -> dict[str, str]:
    matches = list(
        re.finditer(
            r"--update-env-vars=(?P<quote>['\"])(?P<body>[^'\"]*)(?P=quote)",
            deploy_command,
        )
    )
    assert len(matches) == 1, (
        f"{step_id} must contain exactly one quoted --update-env-vars setting"
    )
    environment = {}
    for assignment in matches[0].group("body").split(","):
        name, separator, value = assignment.partition("=")
        assert separator and name and name not in environment, (
            f"{step_id} has an invalid or duplicate --update-env-vars key"
        )
        environment[name] = value
    return environment


def require_settings(
    step_id: str,
    actual: dict[str, str],
    expected: dict[str, str],
) -> None:
    mismatched = sorted(
        key for key, value in expected.items() if actual.get(key) != value
    )
    assert not mismatched, (
        f"{step_id} --update-env-vars missing or mismatched settings: {mismatched}"
    )


def require_quoted_url(
    step_id: str,
    command_text: str,
    variable: str,
    path: str,
) -> None:
    variable_pattern = rf"\$\$?(?:\{{{re.escape(variable)}\}}|{re.escape(variable)})"
    pattern = re.compile(
        rf"(?P<quote>['\"]){variable_pattern}{re.escape(path)}(?P=quote)"
    )
    assert pattern.search(command_text), (
        f"{step_id} must probe exact {variable}{path} URL"
    )


def python_heredoc_bodies(command_text: str):
    lines = command_text.splitlines()
    for index, line in enumerate(lines):
        marker = re.search(
            r"<<-?\s*(?P<quote>['\"]?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
            r"(?P=quote)\s*$",
            line,
        )
        if marker is None or "python" not in line[: marker.start()].casefold():
            continue
        delimiter = marker.group("name")
        for end in range(index + 1, len(lines)):
            if lines[end].strip() == delimiter:
                yield "\n".join(lines[index + 1 : end])
                break


def extract_evidence_program(
    step_id: str,
    command_text: str,
) -> tuple[ast.Module, ast.Dict]:
    assignments = []
    for body in python_heredoc_bodies(command_text):
        try:
            tree = ast.parse(body)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            if any(
                isinstance(target, ast.Name) and target.id == "evidence"
                for target in targets
            ):
                assignments.append((tree, node.value))
    assert len(assignments) == 1, (
        f"{step_id} must assign evidence exactly once"
    )
    tree, value = assignments[0]
    assert isinstance(value, ast.Dict), (
        f"{step_id} evidence assignment must be a dictionary literal"
    )
    assert not any(
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "evidence"
        and isinstance(node.ctx, (ast.Store, ast.Del))
        for node in ast.walk(tree)
    ), f"{step_id} must not mutate the evidence mapping"
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "evidence"
        for node in ast.walk(tree)
    ), f"{step_id} must not mutate the evidence mapping through method calls"
    return tree, value


def call_is_candidate_evidence_write(call: ast.Call) -> bool:
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "write_text":
        return False
    path_call = call.func.value
    return (
        isinstance(path_call, ast.Call)
        and isinstance(path_call.func, ast.Name)
        and path_call.func.id == "Path"
        and len(path_call.args) == 1
        and isinstance(path_call.args[0], ast.Constant)
        and path_call.args[0].value == EVIDENCE_FILE
    )


def call_is_evidence_serializer(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "json"
        and call.func.attr == "dumps"
        and bool(call.args)
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "evidence"
    )


def validate_evidence_emission(step_id: str, tree: ast.Module) -> None:
    imports_json = any(
        isinstance(node, ast.Import)
        and any(alias.name == "json" and alias.asname is None for alias in node.names)
        for node in tree.body
    )
    imports_os = any(
        isinstance(node, ast.Import)
        and any(alias.name == "os" and alias.asname is None for alias in node.names)
        for node in tree.body
    )
    imports_path = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "pathlib"
        and any(alias.name == "Path" and alias.asname is None for alias in node.names)
        for node in tree.body
    )
    assert imports_json and imports_os and imports_path, (
        f"{step_id} must import json, os, and pathlib.Path for evidence emission"
    )

    evidence_loads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "evidence"
        and isinstance(node.ctx, ast.Load)
    ]
    assert len(evidence_loads) == 1, (
        f"{step_id} must consume the evidence mapping only in its approved serializer"
    )

    target_writes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and call_is_candidate_evidence_write(node)
    ]
    assert len(target_writes) == 1, (
        f"{step_id} must write {EVIDENCE_FILE} exactly once"
    )

    write_expressions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and call_is_candidate_evidence_write(node.value)
    ]
    assert len(write_expressions) == 1, (
        f"{step_id} must emit candidate evidence with one direct write expression"
    )
    expected_write = ast.parse(EXPECTED_EVIDENCE_WRITE).body[0]
    assert expression_fingerprint(write_expressions[0]) == expression_fingerprint(
        expected_write
    ), f"{step_id} must serialize the evidence mapping with the approved write form"

    serializers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and call_is_evidence_serializer(node)
    ]
    assert len(serializers) == 1, (
        f"{step_id} must serialize the evidence mapping exactly once"
    )


def validate_evidence_upload(step_id: str, command_text: str) -> None:
    assert not re.search(r"(?<![\w-])gsutil\s+cp(?=\s|$)", command_text), (
        f"{step_id} must use only the approved candidate evidence upload command"
    )
    upload_pattern = re.compile(r"\bgcloud\s+storage\s+cp(?=\s|$)", re.IGNORECASE)
    uploads = [
        segment
        for segment in shell_command_segments(command_text)
        if upload_pattern.search(segment)
    ]
    assert len(uploads) == 1, (
        f"{step_id} must upload candidate evidence exactly once"
    )
    expected_upload = (
        f'gcloud storage cp {EVIDENCE_FILE} "{EVIDENCE_DESTINATION}"'
    )
    assert re.sub(r"\s+", " ", uploads[0]).strip() == expected_upload, (
        f"{step_id} must upload the exact candidate evidence file to the approved path"
    )


def validate_evidence_path_ownership(
    step_id: str,
    command_steps: dict[str, str],
) -> None:
    occurrences = {
        owner_step: command_text.count(EVIDENCE_FILE)
        for owner_step, command_text in command_steps.items()
        if EVIDENCE_FILE in command_text
    }
    assert occurrences == {step_id: 2}, (
        f"{step_id} must be the sole producer and uploader of candidate evidence"
    )


def evidence_bindings(step_id: str, evidence: ast.Dict) -> dict[str, ast.expr]:
    assert len(evidence.keys) == len(evidence.values)
    bindings = {}
    for key_node, value_node in zip(evidence.keys, evidence.values, strict=True):
        assert isinstance(key_node, ast.Constant) and isinstance(key_node.value, str), (
            f"{step_id} evidence keys must be string literals"
        )
        key = key_node.value
        assert key not in bindings, f"{step_id} has a duplicate evidence key"
        bindings[key] = value_node
    return bindings


def expression_fingerprint(expression: ast.AST) -> str:
    return ast.dump(expression, annotate_fields=True, include_attributes=False)


def assert_no_token_like_literals(label: str, text: str) -> None:
    google_api_key_pattern = re.compile(r"AIza[0-9A-Za-z_-]{35}")
    assert google_api_key_pattern.search(text) is None, (
        f"{label} contains a Google API key-like literal"
    )
    jwt_pattern = re.compile(
        r"(?i)(?<![A-Za-z0-9_-])eyj[A-Za-z0-9_-]{8,}"
        r"\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?![A-Za-z0-9_-])"
    )
    assert jwt_pattern.search(text) is None, f"{label} contains a token-like literal"
    for match in re.finditer(
        r"(?P<quote>['\"])(?P<value>[A-Za-z0-9_-]{48,})(?P=quote)",
        text,
    ):
        value = match.group("value")
        if any(character.isalpha() for character in value):
            assert False, f"{label} contains a token-like literal"


def assert_scalar_is_sanitized(
    label: str,
    scalar: str,
    *,
    mapping_key: bool = False,
    secret_container: bool = False,
) -> None:
    compact = re.sub(r"[^a-z0-9]+", "", scalar.casefold())
    for forbidden_identifier in (
        "firebasetoken",
        "appchecktoken",
        "geminiapikeyvalue",
    ):
        assert forbidden_identifier not in compact, (
            f"{label} contains a forbidden sensitive identifier"
        )

    if mapping_key or secret_container:
        assert "geminiapikey" not in compact, (
            f"{label} places a Gemini API key identifier in a value-bearing field"
        )

    without_allowed_secret = scalar.replace(PINNED_GEMINI_SECRET, "")
    assert not re.search(
        r"(?is)--(?:set|update)-secrets(?:\s*=\s*|\s+)"
        r"(?:\\\s*)?GEMINI_API_KEY\b",
        without_allowed_secret,
    ), f"{label} contains a non-pinned Gemini secret binding"
    assert not re.search(
        r"(?i)(?<![A-Za-z0-9])_?GEMINI_API_KEY\s*=\s*",
        without_allowed_secret,
    ), f"{label} contains a direct Gemini API key assignment"

    remaining_gemini_references = re.sub(
        r"--remove-env-vars=GEMINI_API_KEY(?=$|[\s,'\"\\])",
        "",
        without_allowed_secret,
    )
    for check_pattern in (
        r"(?:==|!=)\s*['\"]GEMINI_API_KEY['\"]",
        r"['\"]GEMINI_API_KEY['\"]\s*(?:==|!=)",
        r"['\"]GEMINI_API_KEY['\"]\s+(?:not\s+in|in)\b",
        r"\b(?:not\s+in|in)\s*['\"]GEMINI_API_KEY['\"]",
        r"(?i)['\"]has_gemini_api_key['\"]\]\s+is\s+(?:True|False)",
    ):
        remaining_gemini_references = re.sub(
            check_pattern,
            "",
            remaining_gemini_references,
        )
    assert re.search(
        r"(?i)GEMINI_API_KEY",
        remaining_gemini_references,
    ) is None, f"{label} contains an unsupported Gemini API key reference"
    assert_no_token_like_literals(label, scalar)


def validate_yaml_sensitivity(config) -> None:
    secret_container_names = {
        "env",
        "secretenv",
        "substitutions",
        "availableSecrets".casefold(),
    }
    scalar_index = 0

    def visit(value, *, container_name: str = "") -> None:
        nonlocal scalar_index
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(key, str):
                    scalar_index += 1
                    assert_scalar_is_sanitized(
                        f"cloudbuild.yaml scalar {scalar_index}",
                        key,
                        mapping_key=True,
                    )
                    child_container = key.casefold()
                else:
                    child_container = ""
                visit(child, container_name=child_container)
            return
        if isinstance(value, list):
            for child in value:
                visit(child, container_name=container_name)
            return
        if isinstance(value, str):
            scalar_index += 1
            assert_scalar_is_sanitized(
                f"cloudbuild.yaml scalar {scalar_index}",
                value,
                secret_container=container_name in secret_container_names,
            )

    visit(config)


def assert_command_is_sanitized(step_id: str, command_text: str) -> None:
    assert_scalar_is_sanitized(step_id, command_text)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    config_path = root / "cloudbuild.yaml"
    assert config_path.is_file(), "cloudbuild.yaml must exist"

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert isinstance(config, dict), "cloudbuild.yaml must contain a mapping"
    assert isinstance(config.get("steps"), list), "cloudbuild.yaml must contain steps"
    assert all(
        isinstance(step, dict) and isinstance(step.get("id"), str)
        for step in config["steps"]
    ), "every Cloud Build step must have a string id"
    steps = {step["id"]: step for step in config["steps"]}
    assert len(steps) == len(config["steps"]), "Cloud Build step ids must be unique"

    assert "promote" not in steps, (
        "candidate-only Cloud Build must not have a promote step"
    )

    validate_yaml_sensitivity(config)
    command_steps = {
        step_id: step_command_text(step_id, step)
        for step_id, step in steps.items()
    }
    validate_traffic_commands(command_steps)
    validate_production_service_account_preconditions(command_steps)
    for step_id, command_text in command_steps.items():
        assert "smoke_real_gemini.py" not in command_text, (
            f"{step_id} must not run the real-image candidate smoke upload"
        )

    for required_step in (
        "push-agent",
        "push-web",
        "deploy-agent-candidate",
        "probe-agent-candidate",
        "deploy-web-candidate",
        "probe-web-candidate",
        "write-candidate-evidence",
    ):
        assert required_step in steps, f"missing Cloud Build step: {required_step}"
        assert command_steps[required_step], (
            f"{required_step} must define parsed command args"
        )

    validate_digest_provenance(command_steps)
    validate_exact_gemini_secret_binding(command_steps)

    agent_step_id = "deploy-agent-candidate"
    agent_command = command_steps[agent_step_id]
    agent_deploy = extract_deploy_command(agent_step_id, agent_command)
    for fragment in (
        "--no-traffic",
        '--image="$${agent_ref%:*}@$${agent_digest}"',
        "source-commit=${COMMIT_SHA}",
    ):
        assert fragment in agent_deploy, (
            f"{agent_step_id} deploy command missing exact contract: {fragment}"
        )
    assert "candidate-${SHORT_SHA}" in agent_command, (
        f"{agent_step_id} must create a candidate-${{SHORT_SHA}} tag"
    )
    agent_environment = deploy_environment(agent_step_id, agent_deploy)
    require_settings(
        agent_step_id,
        agent_environment,
        {
            "REQUIRE_REAL_GEMINI": "true",
            "APP_CHECK_REQUIRED": "true",
            "FIREBASE_APP_ID": "${_FIREBASE_APP_ID}",
        },
    )

    web_step_id = "deploy-web-candidate"
    web_command = command_steps[web_step_id]
    web_deploy = extract_deploy_command(web_step_id, web_command)
    for fragment in (
        "--no-traffic",
        '--image="$${web_ref%:*}@$${web_digest}"',
        "source-commit=${COMMIT_SHA}",
    ):
        assert fragment in web_deploy, (
            f"{web_step_id} deploy command missing exact contract: {fragment}"
        )
    assert "candidate-${SHORT_SHA}" in web_command, (
        f"{web_step_id} must create a candidate-${{SHORT_SHA}} tag"
    )
    web_environment = deploy_environment(web_step_id, web_deploy)
    require_settings(
        web_step_id,
        web_environment,
        {"PUBLIC_WEB_ANALYSIS_ENABLED": "false"},
    )

    agent_probe_id = "probe-agent-candidate"
    agent_probe = command_steps[agent_probe_id]
    for path in ("/health", "/ready", "/api/v1/analyze"):
        require_quoted_url(agent_probe_id, agent_probe, "agent_url", path)
    suppressed_header_pattern = re.compile(
        r"(?<!\S)(?:-H|--header)(?:=|[ \t]+)(?P<quote>['\"])"
        r"X-Firebase-AppCheck:\s*(?P=quote)"
    )
    assert suppressed_header_pattern.search(agent_probe) is None, (
        f"{agent_probe_id} must not use colon-only X-Firebase-AppCheck syntax; "
        "curl suppresses that header instead of sending an explicitly empty value"
    )
    assert re.search(
        r"(?<!\S)-H[ \t]+(?P<quote>['\"])"
        r"X-Firebase-AppCheck;(?P=quote)(?=\s|$)",
        agent_probe,
    ), (
        f"{agent_probe_id} must use exact curl syntax "
        "-H 'X-Firebase-AppCheck;' to send an explicitly empty header"
    )
    assert re.search(
        r"\btest\s+['\"]?\$\$?(?:\{status\}|status)['\"]?"
        r"\s+(?:=|==)\s+['\"]?401['\"]?(?=\s|$)",
        agent_probe,
    ), f"{agent_probe_id} must require the exact 401 rejection status"
    assert "APP_CHECK_INVALID" in agent_probe, (
        f"{agent_probe_id} must require stable APP_CHECK_INVALID error code"
    )

    web_probe_id = "probe-web-candidate"
    web_probe = command_steps[web_probe_id]
    for path in ("/", "/ready", "/privacy", "/support"):
        require_quoted_url(web_probe_id, web_probe, "web_url", path)
    assert steps[web_probe_id].get("name") == (
        "gcr.io/google.com/cloudsdktool/cloud-sdk:slim"
    ), f"{web_probe_id} must use the Cloud SDK probe runner"
    assert "curlimages/curl" not in web_probe, (
        f"{web_probe_id} must not use the curl image runner"
    )

    evidence_step_id = "write-candidate-evidence"
    evidence_tree, evidence_node = extract_evidence_program(
        evidence_step_id,
        command_steps[evidence_step_id],
    )
    validate_evidence_emission(evidence_step_id, evidence_tree)
    validate_evidence_upload(
        evidence_step_id,
        command_steps[evidence_step_id],
    )
    validate_evidence_path_ownership(evidence_step_id, command_steps)
    bindings = evidence_bindings(evidence_step_id, evidence_node)
    expected_keys = set(EXPECTED_EVIDENCE_EXPRESSIONS)
    actual_keys = set(bindings)
    missing_keys = sorted(expected_keys - actual_keys)
    extra_keys = sorted(actual_keys - expected_keys)
    assert not missing_keys and not extra_keys, (
        f"{evidence_step_id} evidence key mismatch: "
        f"missing={missing_keys}, extra_count={len(extra_keys)}"
    )

    expected_fingerprints = {
        key: expression_fingerprint(ast.parse(source, mode="eval").body)
        for key, source in EXPECTED_EVIDENCE_EXPRESSIONS.items()
    }
    mismatched_bindings = sorted(
        key
        for key, expression in bindings.items()
        if expression_fingerprint(expression) != expected_fingerprints[key]
    )
    assert not mismatched_bindings, (
        f"{evidence_step_id} evidence has incorrect bindings: {mismatched_bindings}"
    )

    evidence_dump = ast.dump(
        evidence_node,
        annotate_fields=True,
        include_attributes=False,
    )
    compact_evidence = re.sub(r"[^a-z0-9]+", "", evidence_dump.casefold())
    for forbidden_identifier in (
        "geminiapikey",
        "firebasetoken",
        "appchecktoken",
    ):
        assert forbidden_identifier not in compact_evidence, (
            f"{evidence_step_id} contains a forbidden sensitive identifier"
        )
    assert_no_token_like_literals(evidence_step_id, evidence_dump)

    for step_id, command_text in command_steps.items():
        assert_command_is_sanitized(step_id, command_text)

    parsed_config_text = yaml.safe_dump(config, sort_keys=False)
    assert "sumai-gemini-api-key:latest" not in parsed_config_text.casefold()
    assert not re.search(
        r"docker\.pkg\.dev/[^\s'\"]+:latest(?=\s|['\"]|$)",
        parsed_config_text,
        re.IGNORECASE,
    ), "Cloud Build images must not use the latest tag"


if __name__ == "__main__":
    main()
