"""Certification assessment engine backed by SQLite.

Manages three professional certification tracks, administers timed
exams, scores submissions against known-correct answers, and issues
certificates with unique IDs suitable for on-chain EAS attestation.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Track definitions
# ---------------------------------------------------------------------------

CERTIFICATION_TRACKS = {
    "developer": {
        "name": "0pnMatrx Certified Developer",
        "price_usd": 149.00,
        "description": "Proves ability to build plugins, integrate the SDK, and deploy contracts",
        "validity_years": 2,
        "passing_score": 80,
        "questions": 40,
        "time_limit_minutes": 90,
    },
    "auditor": {
        "name": "0pnMatrx Certified Security Auditor",
        "price_usd": 249.00,
        "description": "Proves expertise in Glasswing audit methodology and smart contract security",
        "validity_years": 1,
        "passing_score": 85,
        "questions": 50,
        "time_limit_minutes": 120,
    },
    "enterprise": {
        "name": "0pnMatrx Enterprise Architect",
        "price_usd": 399.00,
        "description": "Proves ability to architect enterprise deployments, multi-chain infrastructure, and plugin ecosystems",
        "validity_years": 2,
        "passing_score": 85,
        "questions": 60,
        "time_limit_minutes": 150,
    },
}

# ---------------------------------------------------------------------------
# Sample question banks (10 per track)
# ---------------------------------------------------------------------------

SAMPLE_QUESTIONS: dict[str, list[dict]] = {
    "developer": [
        {
            "question": "Which Gateway API endpoint converts a natural-language contract description into audited Solidity source code?",
            "options": [
                "POST /api/convert",
                "POST /api/chat",
                "POST /api/audit",
                "POST /api/deploy",
            ],
            "correct_index": 0,
        },
        {
            "question": "In the plugin development lifecycle, which method is called first when the gateway loads a plugin?",
            "options": [
                "get_tools()",
                "on_load()",
                "initialize()",
                "__init__()",
            ],
            "correct_index": 1,
        },
        {
            "question": "When using the Python SDK, which client method retrieves the current subscription tier and usage limits for an authenticated wallet?",
            "options": [
                "client.get_usage()",
                "client.subscription_info()",
                "client.get_subscription()",
                "client.wallet_status()",
            ],
            "correct_index": 2,
        },
        {
            "question": "What is the maximum number of contract conversions per month on the Pro subscription tier?",
            "options": [
                "10",
                "25",
                "50",
                "Unlimited",
            ],
            "correct_index": 2,
        },
        {
            "question": "In the platform config file, under which top-level key are EAS attestation schema UIDs specified?",
            "options": [
                "blockchain.eas",
                "attestations.schemas",
                "contracts.eas_config",
                "eas.schema_uids",
            ],
            "correct_index": 0,
        },
        {
            "question": "What does an EAS attestation UID represent in the context of a certified contract deployment?",
            "options": [
                "The hash of the deployer's wallet address",
                "A unique on-chain reference linking the contract to its audit report",
                "The block number where the contract was deployed",
                "An off-chain identifier stored only in the gateway database",
            ],
            "correct_index": 1,
        },
        {
            "question": "In the contract conversion pipeline, which step occurs immediately after Solidity source generation and before deployment?",
            "options": [
                "Gas estimation",
                "Automated security audit via Glasswing",
                "ABI encoding",
                "Bytecode optimization",
            ],
            "correct_index": 1,
        },
        {
            "question": "Which agent persona is responsible for orchestrating multi-step contract workflows including conversion, audit, and deployment?",
            "options": [
                "Trinity",
                "Morpheus",
                "Neo",
                "Oracle",
            ],
            "correct_index": 2,
        },
        {
            "question": "How does the gateway's rate limiter determine which bucket to decrement when a request arrives?",
            "options": [
                "It checks only the IP address",
                "It uses a composite key of wallet address, API key, and IP address with wallet taking priority",
                "It randomly assigns requests to buckets",
                "It uses only the API key hash",
            ],
            "correct_index": 1,
        },
        {
            "question": "Which database pattern does the platform use to ensure that subscription usage counters are updated atomically without race conditions?",
            "options": [
                "Optimistic locking with version columns",
                "Pessimistic row-level locks via SELECT FOR UPDATE",
                "Atomic UPDATE with SQL arithmetic (SET count = count + 1) and commit=True",
                "Application-level mutex with asyncio.Lock",
            ],
            "correct_index": 2,
        },
    ],
    "auditor": [
        {
            "question": "In a reentrancy attack, what is the core vulnerability that allows an attacker to drain funds from a contract?",
            "options": [
                "The contract uses delegatecall to an untrusted address",
                "The contract updates its state after making an external call, allowing the callee to re-enter before balances are decremented",
                "The contract stores Ether in a mapping instead of a variable",
                "The contract allows anyone to call selfdestruct",
            ],
            "correct_index": 1,
        },
        {
            "question": "Prior to Solidity 0.8, which vulnerability class was caused by arithmetic operations exceeding uint256 bounds without a SafeMath library?",
            "options": [
                "Reentrancy",
                "Front-running",
                "Integer overflow and underflow",
                "Signature malleability",
            ],
            "correct_index": 2,
        },
        {
            "question": "A contract's withdraw() function is marked 'public' but lacks an onlyOwner modifier. What is the most likely exploit?",
            "options": [
                "Anyone can pause the contract",
                "Any address can drain the contract's entire balance by calling withdraw()",
                "The function will revert due to missing gas stipend",
                "The compiler will refuse to deploy it",
            ],
            "correct_index": 1,
        },
        {
            "question": "In a flash loan attack against a DeFi protocol, what enables the attacker to manipulate prices within a single transaction?",
            "options": [
                "The attacker owns a majority of the governance tokens",
                "The protocol relies on a single on-chain AMM pool for price feeds, which the borrowed capital can temporarily distort",
                "Flash loans require collateral that the attacker can forfeit",
                "The attacker exploits a time-locked governance proposal",
            ],
            "correct_index": 1,
        },
        {
            "question": "Which of the following is NOT one of Glasswing's 12-point vulnerability scan categories?",
            "options": [
                "Reentrancy vectors",
                "Access control misconfigurations",
                "CSS injection in frontend dApps",
                "Unchecked external call return values",
            ],
            "correct_index": 2,
        },
        {
            "question": "How does a front-running attack exploit pending transactions in a public mempool?",
            "options": [
                "By submitting a conflicting transaction with a higher gas price so it gets mined first",
                "By calling selfdestruct on the target contract before the victim's transaction lands",
                "By modifying the victim's transaction data in-flight using a man-in-the-middle attack",
                "By bribing validators to exclude the victim's transaction permanently",
            ],
            "correct_index": 0,
        },
        {
            "question": "An oracle manipulation attack is most effective when the protocol does which of the following?",
            "options": [
                "Uses a Chainlink aggregator with multiple independent data sources",
                "Computes a time-weighted average price over a 30-minute window",
                "Reads the spot price from a single DEX pool in the same transaction that uses that price",
                "Fetches prices from an off-chain API via a decentralized oracle network",
            ],
            "correct_index": 2,
        },
        {
            "question": "When auditing a UUPS (Universal Upgradeable Proxy Standard) proxy, which risk is unique compared to a Transparent Proxy?",
            "options": [
                "The proxy admin can front-run user transactions",
                "If the implementation contract's upgrade function is removed or broken in an upgrade, the contract becomes permanently non-upgradeable",
                "Storage layout collisions are impossible with UUPS",
                "UUPS proxies cannot use initializer functions",
            ],
            "correct_index": 1,
        },
        {
            "question": "A developer replaces a require() check with an unchecked block to save gas. Which tradeoff does this represent?",
            "options": [
                "No tradeoff; unchecked blocks are strictly superior",
                "Faster execution at the cost of larger bytecode",
                "Gas savings at the cost of removing overflow/underflow protection, potentially introducing arithmetic vulnerabilities",
                "Improved readability at the cost of slightly higher gas",
            ],
            "correct_index": 2,
        },
        {
            "question": "In a Glasswing audit report, a finding marked 'Critical' with a recommendation of 'Halt deployment' indicates what?",
            "options": [
                "A minor gas optimization opportunity",
                "An informational note about coding style",
                "A vulnerability that can lead to total loss of funds or complete contract compromise if exploited",
                "A suggestion to add NatSpec documentation",
            ],
            "correct_index": 2,
        },
    ],
    "enterprise": [
        {
            "question": "When deploying 0pnMatrx across Ethereum mainnet, Arbitrum, and Base simultaneously, which architectural pattern ensures consistent contract state across chains?",
            "options": [
                "Deploying identical bytecode to all chains and relying on block timestamps for synchronization",
                "Using a hub-and-spoke model with a primary chain as the source of truth and cross-chain message bridges for state sync",
                "Running a single shared database that all chains read from",
                "Disabling contract upgrades on all chains except the primary",
            ],
            "correct_index": 1,
        },
        {
            "question": "In a Kubernetes deployment of the 0pnMatrx gateway, which resource type is most appropriate for the stateless API server pods?",
            "options": [
                "StatefulSet with persistent volume claims",
                "DaemonSet with host networking",
                "Deployment with a Horizontal Pod Autoscaler",
                "CronJob with a 1-minute schedule",
            ],
            "correct_index": 2,
        },
        {
            "question": "The platform's rate limiter uses three bucket types: wallet, API key, and IP. In which order are they evaluated when all three are present?",
            "options": [
                "IP first, then API key, then wallet",
                "Wallet first, then API key, then IP as fallback",
                "All three are checked in parallel and the most restrictive limit applies",
                "API key is the only bucket used when present; the others are ignored",
            ],
            "correct_index": 1,
        },
        {
            "question": "When designing the plugin marketplace, what is the primary mechanism for preventing a malicious plugin from accessing another plugin's data?",
            "options": [
                "Each plugin runs in a shared process but with separate Python namespaces",
                "Plugins are loaded via importlib but share database connections",
                "Each plugin runs in an isolated sandbox with its own scoped database handle and no cross-plugin API access",
                "Plugins sign a terms-of-service agreement that forbids data access",
            ],
            "correct_index": 2,
        },
        {
            "question": "In the NeoSafe multisig revenue routing system, what minimum number of signers must approve a revenue distribution transaction by default?",
            "options": [
                "1 of N",
                "2 of 3",
                "3 of 5",
                "Simple majority (N/2 + 1)",
            ],
            "correct_index": 1,
        },
        {
            "question": "In the A2A (Agent-to-Agent) commerce protocol, how does a purchasing agent verify that a selling agent's service listing is authentic?",
            "options": [
                "By checking the listing's EAS attestation UID against the on-chain schema registry",
                "By pinging the selling agent's IP address directly",
                "By reading the selling agent's README file",
                "By verifying the listing was posted within the last 24 hours",
            ],
            "correct_index": 0,
        },
        {
            "question": "An enterprise customer requires a dedicated gateway instance with custom rate limits. Which subscription tier architecture supports this?",
            "options": [
                "Free tier with a config override file",
                "Pro tier with a shared gateway and higher limits",
                "Enterprise tier with a dedicated gateway deployment, custom TIER_LIMITS, and SLA guarantees",
                "A forked open-source deployment with no subscription at all",
            ],
            "correct_index": 2,
        },
        {
            "question": "Before deploying a production config, what validation step must pass to ensure all required secrets and endpoints are present?",
            "options": [
                "Manual code review of the YAML file",
                "Running the config validator (validate_config()) which checks required keys, URL formats, and secret presence without logging sensitive values",
                "Deploying to staging and waiting for runtime errors",
                "Checking that the config file is under 1 MB",
            ],
            "correct_index": 1,
        },
        {
            "question": "For production observability, which combination of tools provides distributed tracing, metrics, and log correlation for the 0pnMatrx gateway?",
            "options": [
                "Print statements and manual log file grep",
                "Sentry for errors only",
                "OpenTelemetry for distributed tracing, Prometheus for metrics, and structured JSON logging with trace-id correlation",
                "A single Grafana dashboard connected directly to SQLite",
            ],
            "correct_index": 2,
        },
        {
            "question": "Which disaster recovery strategy is appropriate for the gateway's SQLite database in a production enterprise deployment?",
            "options": [
                "No backups needed because SQLite is embedded and always consistent",
                "Daily full backups to the same disk with no off-site copies",
                "Continuous WAL-mode streaming to object storage (S3/GCS) with point-in-time recovery, plus periodic full snapshots to a separate region",
                "Relying on Kubernetes pod restarts to recover from data loss",
            ],
            "correct_index": 2,
        },
    ],
}

# ---------------------------------------------------------------------------
# Certification manager
# ---------------------------------------------------------------------------


class CertificationManager:
    """Administers professional certification exams and issues certificates.

    Manages the full lifecycle: exam start, submission scoring, certificate
    issuance, and public verification.  Backed by SQLite via the platform's
    async database wrapper.
    """

    def __init__(self, db, config: dict | None = None):
        """Initialise with a ``Database`` instance.

        Parameters
        ----------
        db : runtime.db.database.Database
            The platform's shared SQLite wrapper.
        config : dict, optional
            Platform configuration dict.  Reads from the ``certification``
            sub-key for overrides.
        """
        self.db = db
        self.config = config or {}

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the certification tables if they do not exist."""
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS certifications (
                cert_id         TEXT PRIMARY KEY,
                wallet_address  TEXT NOT NULL,
                track           TEXT NOT NULL,
                score           INT,
                passed          BOOLEAN,
                issued_at       REAL,
                expires_at      REAL,
                eas_uid         TEXT,
                status          TEXT DEFAULT 'active'
            )
            """,
            commit=True,
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS cert_attempts (
                id              TEXT PRIMARY KEY,
                wallet_address  TEXT NOT NULL,
                track           TEXT NOT NULL,
                started_at      REAL NOT NULL,
                completed_at    REAL,
                score           INT,
                passed          BOOLEAN,
                answers         TEXT
            )
            """,
            commit=True,
        )

    # ------------------------------------------------------------------
    # Exam lifecycle
    # ------------------------------------------------------------------

    async def start_exam(self, wallet_address: str, track: str) -> dict:
        """Begin a new certification exam attempt.

        Validates that the requested track exists, creates an attempt
        record, and returns metadata the client needs to render the
        exam UI.

        Parameters
        ----------
        wallet_address : str
            The wallet of the candidate taking the exam.
        track : str
            One of ``"developer"``, ``"auditor"``, or ``"enterprise"``.

        Returns
        -------
        dict
            Contains ``attempt_id``, ``track``, ``questions``,
            ``time_limit_minutes``, and ``started_at``.

        Raises
        ------
        ValueError
            If *track* is not a recognised certification track.
        """
        if track not in CERTIFICATION_TRACKS:
            raise ValueError(
                f"Unknown certification track: {track!r}. "
                f"Valid tracks: {', '.join(CERTIFICATION_TRACKS)}"
            )

        track_info = CERTIFICATION_TRACKS[track]
        attempt_id = str(uuid.uuid4())
        now = time.time()

        await self.db.execute(
            """
            INSERT INTO cert_attempts
                (id, wallet_address, track, started_at)
            VALUES (?, ?, ?, ?)
            """,
            (attempt_id, wallet_address, track, now),
            commit=True,
        )

        logger.info(
            "Exam started: attempt=%s wallet=%s track=%s",
            attempt_id,
            wallet_address,
            track,
        )

        return {
            "attempt_id": attempt_id,
            "track": track,
            "questions": track_info["questions"],
            "time_limit_minutes": track_info["time_limit_minutes"],
            "started_at": now,
        }

    async def submit_exam(self, attempt_id: str, answers: list[int]) -> dict:
        """Score a completed exam and issue a certificate if the candidate passes.

        Compares each submitted answer against the correct index in
        ``SAMPLE_QUESTIONS`` for the attempt's track. The score is
        expressed as a percentage of correct answers.  If the score
        meets or exceeds the track's ``passing_score``, a certificate
        row is created.

        Parameters
        ----------
        attempt_id : str
            The UUID returned by :meth:`start_exam`.
        answers : list[int]
            The candidate's selected option indices, one per question.

        Returns
        -------
        dict
            Contains ``passed``, ``score``, ``passing_score``, and
            ``cert_id`` (``None`` when the candidate did not pass).

        Raises
        ------
        ValueError
            If the attempt does not exist or has already been completed.
        """
        row = await self.db.fetchone(
            "SELECT id, wallet_address, track, started_at, completed_at "
            "FROM cert_attempts WHERE id = ?",
            (attempt_id,),
        )
        if not row:
            raise ValueError(f"Attempt not found: {attempt_id}")
        if row["completed_at"] is not None:
            raise ValueError(f"Attempt already completed: {attempt_id}")

        track = row["track"]
        wallet_address = row["wallet_address"]
        track_info = CERTIFICATION_TRACKS[track]
        questions = SAMPLE_QUESTIONS[track]

        # Score: compare each answer to the correct index.  If fewer
        # answers are submitted than questions available, missing
        # answers count as incorrect.
        correct = 0
        total = len(questions)
        for i, q in enumerate(questions):
            if i < len(answers) and answers[i] == q["correct_index"]:
                correct += 1

        score = round((correct / total) * 100) if total > 0 else 0
        passing_score = track_info["passing_score"]
        passed = score >= passing_score
        now = time.time()

        # Persist the attempt result.
        await self.db.execute(
            """
            UPDATE cert_attempts
            SET completed_at = ?, score = ?, passed = ?, answers = ?
            WHERE id = ?
            """,
            (now, score, passed, json.dumps(answers), attempt_id),
            commit=True,
        )

        cert_id: str | None = None

        if passed:
            cert_id = await self._issue_certificate(
                wallet_address, track, score, now
            )

        logger.info(
            "Exam submitted: attempt=%s score=%d passed=%s cert=%s",
            attempt_id,
            score,
            passed,
            cert_id,
        )

        return {
            "passed": passed,
            "score": score,
            "passing_score": passing_score,
            "cert_id": cert_id,
        }

    # ------------------------------------------------------------------
    # Certificate issuance & queries
    # ------------------------------------------------------------------

    async def _issue_certificate(
        self, wallet_address: str, track: str, score: int, issued_at: float
    ) -> str:
        """Create a certification record and return its cert_id.

        The cert_id format is ``CERT-{T}-{YYYY}-{NNNN}`` where *T* is
        the upper-cased first letter of the track, *YYYY* is the
        issuance year, and *NNNN* is a zero-padded sequence number.
        """
        year = datetime.fromtimestamp(issued_at, tz=timezone.utc).year
        prefix = f"CERT-{track[0].upper()}-{year}-"

        # Determine the next sequence number for this track/year.
        count_row = await self.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM certifications WHERE cert_id LIKE ?",
            (f"{prefix}%",),
        )
        seq = (count_row["cnt"] if count_row else 0) + 1
        cert_id = f"{prefix}{seq:04d}"

        track_info = CERTIFICATION_TRACKS[track]
        validity_seconds = track_info["validity_years"] * 365 * 86400
        expires_at = issued_at + validity_seconds

        await self.db.execute(
            """
            INSERT INTO certifications
                (cert_id, wallet_address, track, score, passed,
                 issued_at, expires_at, status)
            VALUES (?, ?, ?, ?, 1, ?, ?, 'active')
            """,
            (cert_id, wallet_address, track, score, issued_at, expires_at),
            commit=True,
        )

        logger.info(
            "Certificate issued: %s for wallet %s (track=%s, score=%d)",
            cert_id,
            wallet_address,
            track,
            score,
        )
        return cert_id

    async def get_certification(self, cert_id: str) -> dict | None:
        """Return full details of a certification, or ``None`` if not found.

        Parameters
        ----------
        cert_id : str
            The certificate identifier (e.g. ``CERT-D-2026-0001``).

        Returns
        -------
        dict or None
        """
        row = await self.db.fetchone(
            """
            SELECT cert_id, wallet_address, track, score, passed,
                   issued_at, expires_at, eas_uid, status
            FROM certifications
            WHERE cert_id = ?
            """,
            (cert_id,),
        )
        if not row:
            return None
        return {
            "cert_id": row["cert_id"],
            "wallet_address": row["wallet_address"],
            "track": row["track"],
            "score": row["score"],
            "passed": bool(row["passed"]),
            "issued_at": row["issued_at"],
            "expires_at": row["expires_at"],
            "eas_uid": row["eas_uid"],
            "status": row["status"],
        }

    async def verify_certification(self, cert_id: str) -> dict:
        """Public verification endpoint — returns a privacy-safe summary.

        The holder's wallet address is truncated to the first 6 and
        last 4 characters.  Timestamps are formatted as ISO-8601 dates.

        Parameters
        ----------
        cert_id : str
            The certificate identifier to verify.

        Returns
        -------
        dict
            Contains ``valid``, ``track``, ``holder_wallet``,
            ``issued``, ``expires``, and ``status``.
        """
        cert = await self.get_certification(cert_id)
        if not cert:
            return {
                "valid": False,
                "track": "",
                "holder_wallet": "",
                "issued": "",
                "expires": "",
                "status": "not_found",
            }

        now = time.time()
        is_expired = now > cert["expires_at"]
        status = "expired" if is_expired else cert["status"]
        valid = status == "active"

        wallet = cert["wallet_address"]
        if len(wallet) > 10:
            truncated_wallet = f"{wallet[:6]}...{wallet[-4:]}"
        else:
            truncated_wallet = wallet

        issued_str = datetime.fromtimestamp(
            cert["issued_at"], tz=timezone.utc
        ).strftime("%Y-%m-%d")
        expires_str = datetime.fromtimestamp(
            cert["expires_at"], tz=timezone.utc
        ).strftime("%Y-%m-%d")

        return {
            "valid": valid,
            "track": cert["track"],
            "holder_wallet": truncated_wallet,
            "issued": issued_str,
            "expires": expires_str,
            "status": status,
        }

    async def list_certifications(self, wallet_address: str) -> list[dict]:
        """Return all certifications for a given wallet.

        Parameters
        ----------
        wallet_address : str
            The wallet to query.

        Returns
        -------
        list[dict]
            A list of certification records, ordered by issuance date
            descending.
        """
        rows = await self.db.fetchall(
            """
            SELECT cert_id, wallet_address, track, score, passed,
                   issued_at, expires_at, eas_uid, status
            FROM certifications
            WHERE wallet_address = ?
            ORDER BY issued_at DESC
            """,
            (wallet_address,),
        )
        return [
            {
                "cert_id": r["cert_id"],
                "wallet_address": r["wallet_address"],
                "track": r["track"],
                "score": r["score"],
                "passed": bool(r["passed"]),
                "issued_at": r["issued_at"],
                "expires_at": r["expires_at"],
                "eas_uid": r["eas_uid"],
                "status": r["status"],
            }
            for r in rows
        ]

    async def get_exam_history(self, wallet_address: str) -> list[dict]:
        """Return all exam attempts for a given wallet.

        Parameters
        ----------
        wallet_address : str
            The wallet to query.

        Returns
        -------
        list[dict]
            A list of attempt records, ordered by start time descending.
        """
        rows = await self.db.fetchall(
            """
            SELECT id, wallet_address, track, started_at,
                   completed_at, score, passed, answers
            FROM cert_attempts
            WHERE wallet_address = ?
            ORDER BY started_at DESC
            """,
            (wallet_address,),
        )
        return [
            {
                "attempt_id": r["id"],
                "wallet_address": r["wallet_address"],
                "track": r["track"],
                "started_at": r["started_at"],
                "completed_at": r["completed_at"],
                "score": r["score"],
                "passed": bool(r["passed"]) if r["passed"] is not None else None,
                "answers": json.loads(r["answers"]) if r["answers"] else None,
            }
            for r in rows
        ]

    async def get_track_info(self, track: str) -> dict | None:
        """Return details about a certification track.

        Parameters
        ----------
        track : str
            The track key (``"developer"``, ``"auditor"``, or
            ``"enterprise"``).

        Returns
        -------
        dict or None
            The track definition from :data:`CERTIFICATION_TRACKS`,
            or ``None`` if the track does not exist.
        """
        info = CERTIFICATION_TRACKS.get(track)
        if info is None:
            return None
        return {**info, "track_key": track}
