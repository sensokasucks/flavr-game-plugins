/*
 * FridgeChatFund
 *
 * Listens for Admin Port Game Script JSON from Stream Core:
 *   {"action":"invest","company":2,"pounds":50000,"from":"Sensoka"}
 *
 * Applies GSCompany.ChangeBankBalance so chat points become in-game cash.
 * Does not touch share slots.
 *
 * Install: copy this folder into OpenTTD/game/ (or content_download/game)
 * then pick FridgeChatFund as the Game Script for the save.
 */

class FridgeChatFund extends GSController
{
    function Start()
    {
        GSLog.Info("FridgeChatFund started — waiting for Stream Core invest packets.");
        this.Sleep(1);
        while (true) {
            this.HandleEvents();
            this.Sleep(10);
        }
    }

    function HandleEvents()
    {
        while (GSEventController.IsEventWaiting()) {
            local ev = GSEventController.GetNextEvent();
            if (ev == null) continue;
            if (ev.GetEventType() != GSEvent.ET_ADMIN_PORT) continue;
            local port = GSEventAdminPort.Convert(ev);
            local obj = port.GetObject();
            if (obj == null) continue;
            this.Apply(obj);
        }
    }

    function Apply(obj)
    {
        local action = "";
        if ("action" in obj) action = obj.action;
        if (action != "invest" && action != "subsidy") return;

        local company = 0;
        local pounds = 0;
        local from = "chat";
        if ("company" in obj) company = obj.company.tointeger();
        if ("pounds" in obj) pounds = obj.pounds.tointeger();
        if ("from" in obj) from = obj.from;
        if (pounds == 0) return;

        if (GSCompany.ResolveCompanyID(company) == GSCompany.COMPANY_INVALID) {
            GSLog.Warning("FridgeChatFund: invalid company " + company);
            return;
        }

        local ok = GSCompany.ChangeBankBalance(
            company,
            pounds,
            GSCompany.EXPENSES_OTHER,
            GSMap.TILE_INVALID
        );
        if (ok) {
            GSLog.Info("FridgeChatFund: " + from + " +" + pounds + " to company " + company);
        } else {
            GSLog.Warning("FridgeChatFund: ChangeBankBalance failed for " + company);
        }
    }

    function Save() { return {}; }
    function Load(version, data) {}
}
