# Free account setup

The public job collection continues to be published by GitHub Actions. Supabase
stores only each user's account baseline, saved/applied/dismissed state, notes,
viewed history, and a small snapshot of jobs they tracked.

1. Create a Supabase Free project; do not enable billing, paid add-ons or uploads.
2. Run `migrations/001_accounts.sql` in its SQL Editor. It creates two tables with
   row-level security and grants authenticated users access only to their rows.
   Anonymous clients cannot read either table. Activity functions derive the
   owner from the signed-in session, never a client-supplied user ID.
3. Set the Site URL and an allowed redirect to
   `https://umarliaquat.github.io/job-scout/`.
4. Configure a Google OAuth web client with the JavaScript origin
   `https://umarliaquat.github.io` and the callback displayed by Supabase's Google
   provider. Request only OpenID, email and profile. Enter the client secret only
   in Supabase. Never commit it or share it in chat.
5. Enable Google in Supabase, then run `python -B account_setup.py` locally. The
   localhost form accepts only the project URL and public publishable/anon key.
   It verifies schema protection, rejects anonymous table access, and checks the
   provider is enabled before writing the public configuration.
6. Build and verify Google sign-in, sign-out, cloud saves and user isolation
   before releasing. A real sign-in test needs the owner's participation.

`web/account-config.js` is deliberately public. The builder rejects secret and
service-role keys. Disabling the configuration prevents account API calls.
Guest browser storage is kept separate; importing it into an account requires
an explicit user confirmation. Existing cloud records win during an import.

The Free project's published allowance and remaining usage must be checked
before expanding usage. No custom SMTP, Gmail access, paid APIs or billing are
needed for Google sign-in. Inactive Free projects may pause.

The public site starts with a welcome screen for signed-out users. Google handles
both signup and login; Browse as guest keeps browser-only tracking available.
Guest mode is remembered for the current tab. A restored account opens the
dashboard directly. The header account menu contains Sign out and Account & data
(import, export and deletion). Signing out returns to the welcome screen.
