class FridgeChatFund extends GSInfo {
    function GetAuthor()      { return "Fridge Workshop"; }
    function GetName()        { return "FridgeChatFund"; }
    function GetDescription() { return "Applies Stream Core chat investments via Admin Port JSON (ChangeBankBalance)."; }
    function GetVersion()     { return 1; }
    function GetDate()        { return "2026-08-27"; }
    function CreateInstance() { return "FridgeChatFund"; }
    function GetShortName()   { return "FCFD"; }
    function GetAPIVersion()  { return "1.4"; }
    function MinVersionToLoad() { return 1; }
}

RegisterGS(FridgeChatFund());
