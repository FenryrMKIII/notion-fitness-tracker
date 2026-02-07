# Remaining Setup Steps

## 1. Create a Notion Integration

1. Go to https://www.notion.so/my-integrations
2. Click **"New integration"**
3. Name it **"Fitness Tracker"**
4. Select your workspace
5. Under Capabilities, grant: **Read content**, **Update content**, **Insert content**
6. Click **Save** and copy the **Internal Integration Token** (starts with `ntn_`)
7. In Notion, open the **Fitness Tracker** page
8. Click the `•••` menu → **"Connect to"** → Select **"Fitness Tracker"**
   - This grants the integration access to all child databases

## 2. Add GitHub Secrets

Go to https://github.com/FenryrMKIII/notion-fitness-tracker/settings/secrets/actions and add:

| Secret | Value |
|--------|-------|
| `HEVY_API_KEY` | Your Hevy API key (from Hevy Settings → API) |
| `NOTION_API_KEY` | The Notion integration token from Step 1 |
| `NOTION_TRAINING_DB_ID` | `13d713283dd14cd89ba1eb7ac77db89f` |
| `GARMIN_EMAIL` | Your Garmin Connect email |
| `GARMIN_PASSWORD` | Your Garmin Connect password |

Or use the CLI:

```bash
gh secret set HEVY_API_KEY -R FenryrMKIII/notion-fitness-tracker
gh secret set NOTION_API_KEY -R FenryrMKIII/notion-fitness-tracker
gh secret set NOTION_TRAINING_DB_ID -R FenryrMKIII/notion-fitness-tracker -b "13d713283dd14cd89ba1eb7ac77db89f"
gh secret set GARMIN_EMAIL -R FenryrMKIII/notion-fitness-tracker
gh secret set GARMIN_PASSWORD -R FenryrMKIII/notion-fitness-tracker
```

After adding secrets, trigger the workflows manually from the **Actions** tab to verify they work.

## 3. Set Up Strava → Notion Zapier Automation

### Prerequisites

- Zapier account (free tier allows 100 tasks/month, sufficient for running)
- Strava account

### Step 3.1: Create a New Zap

1. Go to https://zapier.com/app/zaps
2. Click **"Create Zap"**

### Step 3.2: Configure the Trigger (Strava)

1. Search for **"Strava"** and select it
2. Event: **"New Activity"**
3. Connect your Strava account (authorize Zapier when redirected)
4. Click **"Test trigger"** — verify you see a recent activity with fields like Activity Name, Distance, Moving Time, Start Date, Average Heartrate, Activity ID

### Step 3.3: Add Formatter Steps (Unit Conversion)

Strava returns duration in **seconds** and distance in **meters**. You need two Formatter steps:

**Formatter 1 — Duration to Minutes:**

1. Click **"+"** to add a step after the Strava trigger
2. Search for **"Formatter by Zapier"**
3. Event: **"Numbers"** → **"Perform Math Operation"**
4. Operation: **Divide**
5. Input: select Strava's **Moving Time** field
6. Value: `60`
7. Decimal Places: `1`

**Formatter 2 — Distance to Kilometers:**

1. Add another **"Formatter by Zapier"** step
2. Event: **"Numbers"** → **"Perform Math Operation"**
3. Operation: **Divide**
4. Input: select Strava's **Distance** field
5. Value: `1000`
6. Decimal Places: `2`

### Step 3.4: Configure the Action (Notion)

1. Search for **"Notion"** and select it
2. Event: **"Create Database Item"**
3. Connect your Notion account (grant access to the Fitness Tracker workspace)
4. Database: select **"Training Sessions"**

### Step 3.5: Map Fields

| Notion Property | Map To | Notes |
|----------------|--------|-------|
| **Name** | Strava → Activity Name | Direct mapping |
| **Date** | Strava → Start Date Local | Use local timezone version |
| **Training Type** | Type `Running` (static text) | Or map to Strava's Type field for multi-sport |
| **Duration (min)** | Formatter 1 output | Converted from seconds |
| **Source** | Type `Strava` (static text) | Hard-coded |
| **External ID** | Strava → Activity ID | For deduplication |
| **Distance (km)** | Formatter 2 output | Converted from meters |
| **Avg Heart Rate** | Strava → Average Heartrate | May be empty if no HR monitor |

### Step 3.6: Optional — Add Deduplication Filter

To prevent duplicates if the Zap re-triggers:

1. Before the Notion action, add **"Notion: Find Database Item"**
2. Search Training Sessions where **External ID** equals Strava **Activity ID**
3. Add **"Filter by Zapier"**: only continue if no results found

### Step 3.7: Test and Enable

1. Click **"Test step"** on the Notion action
2. Verify a new entry appears in your Training Sessions database
3. Check all fields are populated correctly
4. Click **"Publish"** to activate the Zap
5. Name it: **"Strava Activity → Notion Training Sessions"**
