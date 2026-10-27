# EXP-0011 operation

This process observes public wallet activity and performs research-only displayed
liquidity simulations. It has no signing, wallet credentials, authenticated orders
or order submission. It never writes to the weather database or restarts its task.

## Start and inspect (PowerShell)

```powershell
Set-Location D:\metar-execution-lab\michupl-pre-metar
uv sync --locked
uv run premetar trader start
# In another terminal:
uv run premetar trader status
uv run premetar trader recent --limit 20
uv run premetar trader shadow
uv run premetar trader analyze
uv run premetar trader stop
```

`start --duration 90 --database data/trader/smoke.sqlite3` is bounded smoke mode.
Default research storage: `data/trader/monitor.sqlite3`; weather path is resolved from `configs/experiments/continuous-v1.json`
(currently `data/continuous-v1.sqlite3`); access uses only `mode=ro` and
`PRAGMA query_only`. Logs rotate at 2MB with three backups beside the
research database. Raw HTTP/WS data are immutable events with hashes. They are
not committed to Git. No research-data deletion policy is enabled. Health warns
at25GB; inspect disk capacity and archive offline before reaching exhaustion.

## Windows logon task

```powershell
uv run premetar trader service-install
uv run premetar trader service-install --no-preview
Start-ScheduledTask -TaskName MichuplPreMetar-TraderShadow-v1
uv run premetar trader service-status
uv run premetar trader stop
uv run premetar trader service-remove --no-preview
```

Preview is the default. The separate task uses the project’s absolute Python,
working directory, current-user interactive logon and Limited privileges; no
password or elevation. It does not run before login. IgnoreNew and an OS-held
research-only lock prevent duplicates. Registration/removal refuses a different
task identity and never touches `MichuplPreMetar-Continuous-v1`. Removal alone
does not stop a running process. Installation does not launch another process;
use `Start-ScheduledTask` after checking status. Restart-on-failure is1minute,
three attempts. A healthy monitor handles recoverable provider failures itself.

## What runs

- Maker-inclusive v2 wallet trades and wallet activity race every3s;
  activity also records REDEEM/merge/split/reward separately. Cursor filters stay fixed;
  max20pages per live pass. Initial last7days are bootstrap-censored.
- Separate resumable full-history pages every10s,1000rows/page, max200pages;
  completion/cursor/end cutoff are recorded. They never trigger copies.
- Data-service freshness and positive taker-only attribution probes every60s.
- Current open daily weather markets refreshed every600s, first1000 Gamma
  candidates plus60 recently traded conditions. Up to256 outcome tokens watched.
  Source recency, not backfill arrival order, determines priority. This is bounded
  coverage, not observation of every weather market or every potential future token.
- Public CLOB market WS preserves full books, deltas and unattributed tape.
  Deltas are not misrepresented as full executable depth. No inference that
  exchange `maker` fields alone reveal economic liquidity role.
- For each prospective target BUY/SELL: delay0/1/3/5/10/30s; fresh REST market
  verification and book captured after the deadline. These are actual later REST
  opportunities, not guaranteed fastest WS fills or fills backdated to the deadline.
  Five-second local queue lateness budget; missed/error/backpressure attempts are
  retained. Book age bound5s. Actual source/detection/request/receipt/creation clocks
  remain separate, upstream trade timestamps have second precision.
- Four independent budgets10/25/50/100USD and three independent exit policies.
  They are alternatives, never one combined capital portfolio. Shared depth within
  one cohort is depleted across lots; separate cohorts are independent scenarios.
- COPY-FOLLOW allocates source SELLs FIFO to copied target BUYs known before that
  SELL detection; delayed copied BUYs may fill before the delayed SELL executes.
  Pre-monitor source inventory is unknown. COPY-TAKE-PROFIT uses frozen
  `min(0.99, entryVWAP+0.05)` and only bids at/above that threshold, sampled10s.
  COPY-HOLD requires captured closed, resolved binary0/1 payout. Settlement is
  idempotent; all original simulated BUYs remain immutable.

## Interpretation and limitations

Startup/restart/outage catchup is censored. No copying old historical rows on
restart. A transaction/token/side group receives at most one copy intent even
when the two feeds partition or round its public rows differently. All original
rows remain retained. Paired endpoint-speed comparisons require both first
receipts to be uncensored; the initial Ankara example preceded activity racing. Interrupted requests become missed; no invented historic execution.
Wallet feed has no unique fill/log ID, so identical economic rows in one transaction
cannot be distinguished. Raw responses retain the evidence. A public market WS
does not identify wallets. Positive exact matches in `taker_only=true` are
API-attributed TAKER evidence, not decoded on-chain roles; absence remains UNKNOWN.
No public order creation time is inferred from execution.

Only explicit captured `feeType=zero_fees` plus `feeSchedule.rate=0` currently
certifies net fees. Nonzero schedules/base_fee alone yield FEE_UNKNOWN, gross
depth estimates only and unknown net economics. This conservative limitation is
intentional; nonzero fee/rounding/version support must be verified before extension.

Context for the four monitored airports is queried as-of detection and uses the
existing strict timestamp policy; stored causal calibration versions are attached
only if already created/trained. Other cities, forecasts and precise settlement
Tmax remain unavailable rather than inferred. Context is not rebranded as
information known at the original historical trade time. Raw market descriptions
retain settlement rules; no automated impossible-outcome claim is enabled.

Source-to-detection age includes chain/indexer/polling/clock effects. Service lag
is recorded independently, not subtracted to manufacture latency precision.
Clock offset is still UNKNOWN. The monitor is a measurable public polling method;
globally fastest wallet attribution is unverified. Resolving position PnL requires
future data; unknown/missing books, fees and unresolved holdings are never wins.
Reports disclose bounded export limits and full recorded counts.
