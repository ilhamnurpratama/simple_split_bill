# Simple Split Bill

A small Streamlit app to split a restaurant bill among people, track items, assign shares, split taxes proportionally, and send summaries (mailto or SMTP with PNG attachment).

This repository contains a single app: `app.py`.

## Features

- Add / update bill items (name, qty, total price).
- Add people (with optional email).
- Assign item quantities to people (additive assign or edit assignments directly).
- Per-person itemized breakdown and totals.
- Add a total tax/service amount and split it proportionally across people.
- Download a PNG summary that includes restaurant, initiator, accounts, and per-person breakdown.
- Open per-person email drafts (mailto) or send emails directly from the app via SMTP (attach PNG).
- Numeric formatting: thousands separators (commas) and no trailing `.00`.

## Quick Start (Windows PowerShell)

1. Create a virtual environment (recommended) and activate it:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install streamlit pandas pillow
```

3. Run the app:

```powershell
streamlit run .\app.py
```

The app will open in your browser. The main UI sections are:

1. Restaurant Information — name, phone, address/notes shown in emails and PNGs.
2. Initiator Information — initiator name and payment accounts.
3. Bill Items — add or update items (qty and total price).
4. Assign Items to People — assign quantities to people (additive).
4a. Edit Current Assignments — edit assigned quantities per person (set exact quantities).
5. Calculation & Send — enter a total tax/service amount, view per-person subtotal/tax/total, download PNG, or email.

## Running without an SMTP provider (development)

If you don't want to send real emails while testing, run a local debug SMTP server that prints messages to console:

```powershell
python -m smtpd -c DebuggingServer -n localhost:1025
```

Then in the app set SMTP host `localhost` and port `1025`. Messages will be printed to the console instead of being delivered.

Alternatively use tools like MailHog or smtp4dev for a nicer UI.

## SMTP providers (recommended)

- Gmail: `smtp.gmail.com` (port 465 SSL or 587 STARTTLS). Use an App Password (recommended) with 2FA enabled.
- SendGrid: `smtp.sendgrid.net` (port 587). Username: `apikey`, Password: `<SENDGRID_API_KEY>`.
- Mailgun, Mailjet, Elastic Email, SMTP2GO, etc. — provider-specific SMTP host/port and credentials.

### Example `st.secrets` configuration (safer than typing credentials every time)

Create a file at `.streamlit/secrets.toml` with:

```toml
[smtp]
server = "smtp.sendgrid.net"
port = 587
username = "apikey"
password = "YOUR_SENDGRID_API_KEY"
from_email = "you@example.com"
```

In the app you can prefer `st.secrets` over UI fields for SMTP credentials. (The app currently reads SMTP from the UI fields; updating it to read from `st.secrets` is easy if you want.)

## Notes on behavior & validation

- Items are updated when you add an item with an existing name (so you can fix qty/price typos).
- When you assign quantities via the Assign form, the values are additive (the app adds the given qty to the current assigned amount).
- Use the "Edit Current Assignments" section to set exact assigned quantities per person (useful for corrections). Setting a value to `0` removes the assignment.
- Tax splitting: enter a total tax/service amount in section 5; it is split proportionally by subtotal (each person's subtotal / total_sub * tax_total).
- Numeric formatting shows thousands separators and hides trailing `.00` for cleaner display.

## Email subjects and bodies

- Mailto drafts now include the restaurant name in the subject (if provided):

```
Split Bill Summary: <Restaurant Name>
```

- Emails sent via SMTP also use the same subject (if you enable the SMTP send feature).
- Email bodies include the restaurant header (name/address/phone), a per-item breakdown, subtotal, tax share, and total.

## Image summary

The downloaded PNG contains:

- Restaurant info (if provided)
- Initiator and payment accounts
- Per-person totals and itemized lines

## Troubleshooting

- If the "Edit Current Assignments" section doesn't appear, make sure you have at least one item and one person added — the editor only shows when both exist.
- If SMTP sending fails, check:
	- Credentials are correct
	- Port selection (465 for SSL, 587 for STARTTLS)
	- Provider requires an app password or special API key (e.g., Gmail)
	- Use local debug server for testing

## Security

- Avoid hardcoding SMTP credentials in source or committing them. Use `st.secrets` or environment variables.
- The app currently sends emails directly via SMTP if you provide credentials in the UI; consider using a dedicated email service (SendGrid, Mailgun) for production.

## Development notes

- Main file: `app.py`
- Dependencies: `streamlit`, `pandas`, `pillow` (PIL)
- Python 3.8+

## Contributing / Changes

If you want any of these features added or changed, I can help implement:

- Option to split tax equally (instead of proportionally)
- Add restaurant logo upload and include logo in the PNG
- Rename/delete items and accounts UI
- Persist sessions to disk or export/import session JSON