# DETOMSITE SMS Forwarding Agent (Android)

Sits on the **shopkeeper's phone** and turns the shop's bank credit SMS into an
automatic order confirmation — no student input, no human watching.

## What it does

1. The student scans the shop's UPI QR and pays.
2. The **shop's bank** sends a credit SMS (with the UTR + amount) **to the
   shop's phone**.
3. This app reads the SMS **on-device**, extracts only the **UTR + amount**
   locally (the raw SMS text — sender, balance, account — never leaves the
   phone), and posts the minimal proof to `POST /api/v1/local/sms/match`.
4. The backend matches **amount + shop phone** against a pending UPI order,
   stores the UTR, marks the payment `Success`, sets the order `Confirmed`,
   and auto-fires the shop's WhatsApp notification.
5. The shop just taps **Confirm** later → order becomes `Completed`.

The whole payment-verification step becomes fully automatic.

## Setup

1. Open this folder in Android Studio and build the `app` module.
2. Install the APK on the **shopkeeper's phone** (the one registered on the
   shop's bank account — the number that receives the credit SMS).
3. Open the app, fill in:
   - **Backend API URL** — e.g. `https://your-api.onrender.com`
   - **Agent key** — the same value you set for `SMS_FORWARD_KEY` in the
     backend `.env`
   - **Shop phone** — optional; leave empty to auto-read from the SIM. Set it
     if the SIM reads blank.
4. Tap **Grant SMS permission** (both `RECEIVE_SMS` + `READ_SMS`, and on
   Android 13+ notifications). Some phones need the app set as a **default SMS
   app** or battery-unrestricted for reliable background delivery.
5. Tap **Save**.

## Server side

Add to the backend `.env`:

```
SMS_FORWARD_KEY=<your-secret-agent-key>
```

This key must match what the app sends in the `X-Agent-Key` header. When the
key is set, `/api/v1/local/sms/match` rejects submissions without it; when
it is empty (dev/demo), the endpoint stays open for manual testing.

## Bank SMS formats matched

The agent reads any SMS containing a strong credit keyword (`credited`,
`deposited`, `received`, `rcvd`) and **not** a debit keyword (`debited`,
`deducted`), extracts a 8–30 char UTR / reference code, and picks the credited
amount nearest to the credit phrase (so a `Bal: Rs 5,000` line is never chosen
over the `Rs 80` credit). Typical:

```
Rs.80.00 credited to Ravi Cafe A/c XX1234 via UPI. UTR: ABC123456789. Bal Rs. 5,000.
```

The backend then confirms the matching `Pending Payment` order for that shop
where the credited amount equals the order total. If two pending orders for the
same shop share the exact same amount it confirms the newest one and logs both
so nothing is silently missed.

## Failure modes

- No match yet → the proof is logged and the order stays `Pending Payment`.
  It still auto-confirms the moment a matching amount+UTR proof arrives.
- Agent offline → order stays `Pending Payment`; the shopkeeper can still tap
  **Payment Received** in the shop app as before (nothing removes that path).