# The Dent Trooper (MVP)

Mobile-first internal operations web app for a paintless dent repair business.

## Stack choices
- **Python 3 stdlib WSGI app** + **SQLite** for zero-dependency setup in this environment.
- Mobile-first server-rendered HTML/CSS with large tap targets and bottom nav.
- Relational schema covering users, leads, customers, vehicles, jobs, estimates/invoices, notes, photos, templates, and activity logs.

## MVP included
- Session auth + admin seed user.
- Dashboard quick links and upcoming jobs.
- Leads CRUD + lead status + convert lead to job.
- Customers with flag warning, linked vehicles/jobs.
- Vehicles linked via customer and job relations.
- Jobs CRUD, scheduling, simple double-booking guard, activity timeline.
- Calendar/upcoming view.
- Estimates with line items, convert to invoice, invoice status updates.
- Print-friendly estimate/invoice pages (PDF via browser print).
- Before/after photo uploads for jobs.
- Internal notes on jobs.
- Message templates table seeded for future SMS/email integration.
- Mileage manual per job.

## Run locally
```bash
python app.py
```
Then open `http://localhost:8000`.

Demo login:
- `admin@denttrooper.local`
- `changeme123`

## Test
```bash
pytest -q
```

## Data model
Tables:
- users, sessions
- customers, vehicles
- leads
- jobs
- estimates, estimate_line_items
- invoices, invoice_line_items
- notes
- job_photos
- message_templates
- activity_logs

## Architecture notes
- Organized by route + table-centric operations for MVP speed.
- `has_conflict` enforces basic one-tech no-double-book at same datetime.
- Lead conversion creates customer, vehicle, and linked job.
- Photo storage uses local filesystem path references (`uploads/`).

## Next recommended steps
1. Move to framework with migrations + typed models (FastAPI/Django/Next + ORM).
2. Add CSRF protection, stricter auth and password reset.
3. Add robust forms/UI components and per-entity note UIs.
4. Add webhook/API endpoint for WordPress estimate submission.
5. Add VIN decode integration + richer reporting + SMS/email provider integration.
