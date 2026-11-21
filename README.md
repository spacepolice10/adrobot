# Adrobot

FastAPI with SQLAlchemy 2 and a small Alpine.js frontend. Pydantic defines the
API response schema. The frontend is served by FastAPI and loads a pinned
Alpine.js release from jsDelivr.

## Local development

With Docker Desktop running and [mise](https://mise.jdx.dev/) installed, run:

```sh
mise trust
mise install
cp .env.example .env
```

Fill in the Keitaro settings in `.env`, then run `./bin/live`. The script
starts the local PostgreSQL service, applies the draft schema, and starts
Adrobot. Export `DATABASE_URL` before running it to use an existing database
instead of starting PostgreSQL through Compose.

Open <http://127.0.0.1:8000/> for the frontend or
<http://127.0.0.1:8000/docs> for interactive API documentation.

Check the database connection at <http://127.0.0.1:8000/api/health>.
Compose uses a dedicated volume for PostgreSQL. The credentials in
`compose.yaml` are for local development. Run `docker compose stop postgres`
to stop the service while keeping the data.

From the project root, run `mise exec -- uv run alembic upgrade head` to upgrade to the latest
Alembic revision. The baseline also adopts an existing draft table created by
the original setup command and preserves its rows. Run it with the same
`DATABASE_URL` as the app. If the app is already running against that database,
you can run the migration in a separate terminal and refresh the campaign page.
If you omit `DATABASE_URL`, the app uses `adrobot.db` in the working directory.

## Checks

```sh
mise exec -- uv run pytest
mise exec -- uv run ruff check .
mise exec -- uv run ruff format --check .
```

## Application structure

| Location under `adrobot/` | Responsibility |
| --- | --- |
| `main.py` | Assemble the app, mount static assets, and manage the lifetimes of the database engine and Keitaro client. |
| `controllers/` | Handle incoming HTTP requests and return HTML, redirects, or JSON. |
| `forms/` | Validate submitted fields and run the requested campaign or offer action through `submit`. |
| `models/offer_draft.py` | Own one offer draft per campaign, from the first local edit through refresh, publication, and confirmation. |
| `keitaro/` | Build outbound tracker requests and interpret Keitaro responses. |
| `db.py` and `migrations/` | Provide database engines and sessions, and version the local schema. |

## Naming conventions

- **Controllers** use the module as the resource name. `campaigns.index` lists
  campaigns, `campaigns.new` shows the form, `campaigns.create` handles its submission,
  and `campaigns.show` displays one campaign. Give custom actions names that describe
  what happens, such as `campaigns.show_archive_confirmation` and `campaigns.archive`.
- **Keitaro functions** name the operation and its target. Use `get_campaign` for one
  record by ID, `list_campaign_streams` for a collection, and `search_offers` for
  user-supplied search criteria. Use a write verb such as `replace_stream_offers` when
  the call changes the tracker.
- **Campaign offer drafts** name each operation. On `CampaignOfferDraft`,
  `add_offer`, `remove_offer`, `restore_offer`, `pin_offer`, and `unpin_offer` each
  require a stream ID and an offer ID. `refresh` merges the campaign's published
  assignments into the draft. `publish` sends pending changes to Keitaro and records
  confirmation. The campaign page reads the saved state with `load_snapshot`.
- **Forms and pickers** share verbs for shared behavior. Both Python form objects expose
  `submit`. In the browser, `setOfferQuery` changes the search text and clears the
  selection, while `selectOffer` chooses a match. The country picker uses the same pair
  of verbs.
- **Checks and resources** use `is_` or `has_` for boolean questions, `validate_` for
  model validators, and `require_` for request guards that raise on failure.
  `create_database_engine` constructs an engine, `open_keitaro_client` owns a client for
  the duration of a context, and `get_keitaro_client` retrieves the application's
  client.

## Keitaro campaign creation

Copy `.env.example` to `.env` in the project root and fill in
`KEITARO_URL` (the tracker URL) and `KEITARO_API_KEY` (an Admin API key).
Git ignores `.env`.

Start the app with the live Keitaro settings from `.env`:

```sh
./bin/live
```

Open `/campaigns` to view the current campaign list, or `/campaigns/new`
to create one. Enter the name and country code, then select a Keitaro offer
from the search suggestions.

Adrobot looks up the campaign domain, the `FORTESTS` campaign group and the
`FORTESTS` traffic source in Keitaro. Set `KEITARO_CAMPAIGN_DOMAIN_ID` in
`.env` to the domain ID shown in Keitaro. Adrobot verifies that domain is
active before creating the campaign. If no ID is set, Adrobot looks up the
domain by `KEITARO_CAMPAIGN_DOMAIN`, which defaults to `in.posdk.xyz`.
The campaign starts disabled and is
enabled after both flows are created. The first flow redirects the selected
country to Google, and the default flow sends the rest to the selected offer.
After successful creation, the form redirects back to the campaign list.

Campaign form POSTs require a same-origin browser signal. For scripted
requests, send the app origin in the `Origin` header. Behind a reverse proxy,
preserve the public Host and configure Uvicorn to trust scheme forwarding
only from that proxy. Responses include an `X-Request-ID` for matching
tracker and draft failures to application logs.

## Offer drafts

Open a campaign and select **Обновить офферы из Keitaro** to import its flows
and offers. Adding, removing, restoring and pinning offers edits the local
draft. A new stream assignment is saved as `Pending`. It becomes `active`
when Keitaro confirms that the assignment is active. Removing an unpublished
addition cancels it. Removing a published assignment marks it `Removed` until
sync confirms its removal. A refresh also retains assignments that disappeared
in Keitaro as `Removed` so they can be restored. Both pending and active
assignments count toward the intended traffic split. Unpinned assignments
divide the share left after pinned assignments. Whole percentages are rounded with any remainder assigned by offer ID.
Select **Синхронизировать с Keitaro** to publish the active offer list for
each changed stream. Adrobot checks for edits in Keitaro since the last
refresh and keeps the local draft if publication fails. Existing drafts
from before synchronization was added may need a refresh first.

## Test offer

From the project root, run `mise exec -- uv run python -m adrobot.create_test_offer`
to create **Adrobot Test Offer 2** in the configured Keitaro catalog. If an offer
with that name already exists, the script prints its ID. It reads the connection
settings from `.env` and only interacts with the offer catalog.

## Run with a local Keitaro mock

Run both the mock and Adrobot from the project root:

```sh
./bin/demo
```

Open <http://127.0.0.1:8001/campaigns/42>. **Demo Offer A** is already attached.
The catalog contains **Demo Offer A** through **Demo Offer L** (IDs 7–18).
Add **Demo Offer B**, check the 50/50 shares, then synchronize. The demo does
not use the live Keitaro credentials or database. The mock simulates the Admin
API, including campaign and stream changes. It does not serve tracking links
or calculate traffic statistics. Ctrl+C stops both processes and discards the
temporary SQLite database. Each run starts with fresh demo data. If the
default ports are occupied, set `ADROBOT_MOCK_PORT` and `ADROBOT_DEMO_PORT`.
