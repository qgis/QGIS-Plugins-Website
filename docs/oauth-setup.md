# OAuth Provider Setup

Each provider needs a **SocialApp** entry in the Django Admin.  
Go to: **Admin → Social Accounts → Social applications → Add social application**

Fields to fill:
- **Provider** — select from the dropdown
- **Name** — any label (e.g. "GitHub")
- **Client ID** — the OAuth App ID / Client ID from the provider
- **Secret key** — the OAuth Secret from the provider
- **Key** — only required for Apple (the Key ID, see below)
- **Settings** — optional JSON for provider-specific options (e.g. Apple's `certificate_key`)
- **Sites** — move your site (e.g. `example.com`) from "Available" to "Chosen"

---

## GitHub

1. Go to <https://github.com/settings/developers> → **OAuth Apps** → **New OAuth App**
2. Fill in:
   - **Application name**: QGIS Plugins (or any label)
   - **Homepage URL**: `https://plugins.qgis.org`
   - **Authorization callback URL**: `https://plugins.qgis.org/accounts/github/login/callback/`
3. Click **Register application**, then **Generate a new client secret**.
4. In Django Admin:
   - Provider: `GitHub`
   - Client ID: the **Client ID** shown on the app page
   - Secret key: the **Client secret** you just generated

---

## Google

1. Go to <https://console.cloud.google.com/> → Select or create a project.
2. Navigate to **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
3. Set **Application type** to **Web application**.
4. Add to **Authorized redirect URIs**:
   ```
   https://plugins.qgis.org/accounts/google/login/callback/
   ```
5. Click **Create**. Note the **Client ID** and **Client secret**.
6. In Django Admin:
   - Provider: `Google`
   - Client ID: the Client ID
   - Secret key: the Client secret

> You may also need to enable the **Google People API** under **APIs & Services → Library**.

---

## GitLab

### GitLab.com (default)

1. Go to <https://gitlab.com/-/user_settings/applications> → **Add new application**.
2. Fill in:
   - **Name**: QGIS Plugins
   - **Redirect URI**: `https://plugins.qgis.org/accounts/gitlab/login/callback/`
   - **Scopes**: check `read_user`
3. Click **Save application**. Note the **Application ID** and **Secret**.
4. In Django Admin:
   - Provider: `GitLab`
   - Client ID: the Application ID
   - Secret key: the Secret

### Self-hosted GitLab instance

Uncomment and edit the `gitlab` section in `qgis-app/settings_local.py`
(copy from `settings_local.py.templ`):

```python
SOCIALACCOUNT_PROVIDERS = {
    "gitlab": {
        "GITLAB_URL": "https://your-gitlab.example.com",
        "SCOPE": ["read_user"],
    },
}
```

Then create the OAuth application on your self-hosted instance at  
`https://your-gitlab.example.com/-/profile/applications`.

---

## OpenStreetMap

1. Go to <https://www.openstreetmap.org/user/YOUR_USERNAME/oauth_clients/new>  
   (replace `YOUR_USERNAME` with your OSM username).
2. Fill in:
   - **Name**: QGIS Plugins
   - **Main Application URL**: `https://plugins.qgis.org`
   - **Callback URL**: `https://plugins.qgis.org/accounts/openstreetmap/login/callback/`
   - **Permissions**: check **Read user preferences**
3. Click **Register**. Note the **Consumer Key** and **Consumer Secret**.
4. In Django Admin:
   - Provider: `OpenStreetMap`
   - Client ID: the Consumer Key
   - Secret key: the Consumer Secret

> OSM uses OAuth 1.0a — django-allauth handles this transparently.

---

## Microsoft

1. Go to <https://portal.azure.com/> → **Microsoft Entra ID → App registrations → New registration**.
2. Fill in:
   - **Name**: QGIS Plugins
   - **Supported account types**: *Accounts in any organizational directory and personal Microsoft accounts* (for `"tenant": "common"`)
   - **Redirect URI**: Web — `https://plugins.qgis.org/accounts/microsoft/login/callback/`
3. Click **Register**. Note the **Application (client) ID**.
4. Go to **Certificates & secrets → New client secret**. Note the **Value** (only shown once).
5. Go to **API permissions → Add a permission → Microsoft Graph → Delegated → User.Read** → Grant admin consent.
6. In Django Admin:
   - Provider: `Microsoft`
   - Client ID: the Application (client) ID
   - Secret key: the client secret Value

> To restrict to a specific tenant (organisation), change `"tenant": "common"` to your **Directory (tenant) ID** in `settings_local.py`.

---

## Apple

Apple Sign In requires extra steps compared to other providers.

### Prerequisites
You need an Apple Developer account (<https://developer.apple.com>).

### Steps

1. **Create an App ID**:
   - Go to **Certificates, Identifiers & Profiles → Identifiers → +**
   - Type: **App IDs** → **App**
   - Enable **Sign In with Apple**
   - Note the **Bundle ID** (e.g. `org.qgis.plugins`)

2. **Create a Services ID** (this is the OAuth client):
   - Go to **Identifiers → +** → **Services IDs**
   - Description: QGIS Plugins
   - Identifier: e.g. `org.qgis.plugins.web` (must be unique, different from Bundle ID)
   - Enable **Sign In with Apple → Configure**:
     - Primary App ID: select the App ID from step 1
     - Domains: `plugins.qgis.org`
     - Return URLs: `https://plugins.qgis.org/accounts/apple/login/callback/`
   - Note the **Services ID** identifier — this is your **Client ID**

3. **Create a Key**:
   - Go to **Keys → +**
   - Enable **Sign In with Apple → Configure** → select your Primary App ID
   - Click **Register** and **Download** the `.p8` file (only downloadable once)
   - Note the **Key ID**

4. In Django Admin:
   - Provider: `Apple`
   - Client ID: the **Services ID** identifier (e.g. `org.qgis.plugins.web`)
   - Secret key: your **Team ID** (found top-right in the developer portal, 10 chars)
   - Key: the **Key ID** shown on the key detail page (10-char identifier, not the `.p8` content)
   - Settings: paste the following JSON, replacing the value with the full content of your `.p8` file with newlines as `\n`:
     ```json
     {
       "certificate_key": "-----BEGIN PRIVATE KEY-----\nMIGH...\n-----END PRIVATE KEY-----"
     }
     ```

   django-allauth uses the Team ID + Key ID + `.p8` content to generate a JWT client secret dynamically. All credentials are stored in the database via Admin — no changes to `settings_local.py` are required for Apple.

---

## LinkedIn

1. Go to <https://www.linkedin.com/developers/apps/new> → Create an app.
2. Fill in the required fields (App name, LinkedIn Page, logo).
3. After creation, go to the **Auth** tab:
   - Note the **Client ID** and **Client Secret**
   - Add to **Authorized redirect URLs for your app**:
     ```
     https://plugins.qgis.org/accounts/linkedin_oauth2/login/callback/
     ```
4. Go to the **Products** tab → Request access to **Sign In with LinkedIn using OpenID Connect**.
5. In Django Admin:
   - Provider: `LinkedIn`
   - Client ID: the Client ID
   - Secret key: the Client Secret

> The `openid`, `profile`, and `email` scopes configured in settings require the **OpenID Connect** product to be approved. Standard OAuth2 (`r_liteprofile`, `r_emailaddress`) also works but uses the legacy `linkedin` provider.

---

## Telegram

Telegram uses a **Login Widget** rather than standard OAuth. There is no redirect URI.

1. Open Telegram and message **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot` and follow the prompts to create a bot. Note the **bot token** (format: `123456789:ABC-...`).
3. Send `/setdomain` to BotFather, select your bot, and enter your domain: `plugins.qgis.org`.
4. In Django Admin:
   - Provider: `Telegram`
   - Client ID: your **bot username** (without `@`, e.g. `QGISPluginsBot`)
   - Secret key: the **bot token** (e.g. `123456789:ABC-...`)

> The Telegram provider works via a login widget that calls back to  
> `https://plugins.qgis.org/accounts/telegram/login/callback/`.  
> No client secret registration on a portal is needed — the bot token itself signs the payload.

---

## Callback URLs Summary

| Provider     | Callback URL |
|---|---|
| GitHub | `/accounts/github/login/callback/` |
| Google | `/accounts/google/login/callback/` |
| GitLab | `/accounts/gitlab/login/callback/` |
| OpenStreetMap | `/accounts/openstreetmap/login/callback/` |
| Microsoft | `/accounts/microsoft/login/callback/` |
| Apple | `/accounts/apple/login/callback/` |
| LinkedIn | `/accounts/linkedin_oauth2/login/callback/` |
| Telegram | `/accounts/telegram/login/callback/` |

Prepend your domain, e.g. `https://plugins.qgis.org/accounts/github/login/callback/`.

For local development replace the domain with `http://localhost:8000` and register a separate OAuth app (or add `localhost` as an allowed redirect on the existing one).
