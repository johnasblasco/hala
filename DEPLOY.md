# Deploying Hala online (Vercel + Supabase)

Running locally with `hala serve` needs none of this. Follow these steps only
to use Hala from anywhere (your phone, your partner's laptop).

| Piece | Where it runs | What it does |
|---|---|---|
| `web` service | Vercel | The React app (everything except the paths below) |
| `app` service | Vercel | The Python API: `/api/*` and the public `/reports/*` and `/preview/*` pages |
| Database | Supabase Postgres | Leads, settings and search progress (in a private `hala` schema) |
| Login | Supabase Auth | Email + password, limited to emails you allow |

## 1. Supabase (about 5 minutes)

1. **Get the database connection string.** In your project, click **Connect**
   and copy the **Transaction pooler** URI (port `6543`). Replace
   `[YOUR-PASSWORD]` with your database password. This is your `DATABASE_URL`.
2. **Get the API details.** Under **Project Settings → API** (or **API Keys**),
   copy the **Project URL** (your `SUPABASE_URL`) and the **anon / publishable**
   key (your `SUPABASE_ANON_KEY`). Never use the `service_role` / secret key here.
3. **Turn off public sign-ups.** Under **Authentication → Sign In / Providers**,
   turn off *Allow new users to sign up*.
4. **Create your login.** Under **Authentication → Users → Add user**, add your
   email and a password (tick *Auto confirm*). Repeat for your partner.

Hala creates its own tables on first start. They live in a separate `hala`
schema with row level security on, so Supabase's public API (the anon key)
can't read them. Only the server's database connection can.

## 2. Vercel

1. **Import** the GitHub repo `johnasblasco/hala` as a new project. Vercel reads
   `vercel.json` and sets up both services.
2. Under **Settings → Environment Variables**, add:

   | Name | Value | Required |
   |---|---|---|
   | `DATABASE_URL` | Supabase transaction pooler URI | yes |
   | `SUPABASE_URL` | `https://<project>.supabase.co` | yes |
   | `SUPABASE_ANON_KEY` | anon / publishable key | yes |
   | `HALA_ALLOWED_EMAILS` | `you@gmail.com,partner@gmail.com` | yes |
   | `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENROUTER_API_KEY` / `OPENAI_API_KEY` | AI writing for emails and previews (or paste the key in Settings) | no |
   | `HALA_AI_PROVIDER` | `anthropic`, `gemini`, `groq`, `openrouter`, `openai` or `custom` (else the one with a key) | no |
   | `GOOGLE_MAPS_API_KEY` | for bigger lead lists | no |
   | `HALA_SMTP_USER` / `HALA_SMTP_PASSWORD` | Gmail address + App Password for the Send button (or set in Settings) | no |
   | `HALA_PUBLIC_URL` | your custom domain, e.g. `https://app.yourstudio.com` | no |

   Without the login settings, the deployed API refuses every request, so it
   can never be left open by accident.
3. **Deploy.** The code is currently on the branch `claude/shared-session-f5legi`.
   Either merge it into `main`, or set that branch as the production branch
   under **Settings → Git**.
4. Open your Vercel URL and log in with the user from step 1.4.

## Accounts and workspaces

Each email in `HALA_ALLOWED_EMAILS` gets its **own private workspace**: its own
leads, searches, settings, API keys and Gmail sending. Accounts can't see each
other's data. Data created before workspaces existed belongs to the **first**
email in the list.

API keys set as Vercel environment variables (e.g. `GEMINI_API_KEY`) are a
fallback for **every** account. For separate businesses, have each account
paste its own keys in Settings instead.

## How it behaves online

- **Report links in emails** point at `https://<your-domain>/reports/<random-id>`.
  Those pages are public (the business owner opens them from the email), but
  the IDs can't be guessed. You don't need Cloudflare Pages.
- **Searches** run in small steps your browser drives, because Vercel stops a
  function once it responds. Keep the Find leads tab open while a search runs.
  If you close it, reopen the page and it carries on from where it stopped.
- **API keys** typed into Settings are stored in your Supabase database.
  Setting them as Vercel environment variables instead keeps them out of the
  database.

## Test locally first (optional)

```bash
vercel env pull .env.local   # after adding the variables above
vercel dev                   # runs both services with the same routing as production
```
