# Vaelon and accounting software

Vaelon keeps bills, invoices, a budget and deals itself. To work WITH an accounting program, there are two ways.

## 1. Connected tools (MCP) - for programs that have an MCP server

Vaelon is an MCP client (`vaelon mcp add`). A program that publishes an MCP server can be connected; its tools then
appear in Vaelon (group "Connected tools"), each call needs your approval, and every tool is pinned so a changed tool
is blocked until you allow it again. In company mode only the **owner** and the **accountant** may use connected
tools.

Known MCP servers (checked 2026-11-15 - check their pages for the current setup before installing):

| Program | Server | Notes |
|---|---|---|
| Xero | `@xeroapi/xero-mcp-server` (by Xero, MIT) | Node.js 18+; a Xero "custom connection" (client id + secret) or a bearer token |
| QuickBooks Online | `github.com/intuit/quickbooks-online-mcp-server` (by Intuit) | runs locally; needs an app in the Intuit Developer Portal (OAuth 2.0); sandbox first |

Example (Xero) - the keys are passed by name, never typed into the chat (`vaelon key set` asks "Save anyway?" for a
name it does not know - answer y):

```
vaelon key set XERO_CLIENT_ID
vaelon key set XERO_CLIENT_SECRET
vaelon mcp add xero --env XERO_CLIENT_ID=XERO_CLIENT_ID --env XERO_CLIENT_SECRET=XERO_CLIENT_SECRET -- npx -y @xeroapi/xero-mcp-server@latest
vaelon mcp list
```

Then ask, for example, "list the unpaid invoices in Xero" - Vaelon shows each call for approval first.

Other accounting programs: no MCP server was found for them. Use Money > Export to Excel and import the sheet there.

## 2. Files for the accountant

Money > Paid > **Export to Excel** (or "save the bills for the accountant") writes one workbook with the bills,
the invoices, the budget and the deals of the open company. In company mode the journal (who changed what) can be read
in Money > Company; it is encrypted and its chain shows whether anything was changed outside Vaelon.

## What Vaelon never does

It never pays, never logs in to a bank and never sends anything to an accounting program without your approval of
that exact call.
