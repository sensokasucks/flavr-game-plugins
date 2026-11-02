// FridgeRegulars: ten extra customers ("Regular 1" .. "Regular 10") so a busy chat has more
// customers to carry names. A separate MelonLoader mod (FridgeRegulars.dll) next to FridgeSchedule1.dll,
// because S1API creates every custom NPC class it finds in a loaded mod: leaving this DLL out is
// the off switch.
//
// They are real NPCs made with S1API (github.com/ifBars/S1API, docs/custom-npcs.md): S1API registers
// them with the game, saves them in the save (neutral names only; chatter names are put on by
// FridgeSchedule1's CustomerWatcher on each player's screen, like on any customer) and networks them
// to co-op players, who all need this DLL too. A save that has met them expects this mod; removing
// it later leaves those customers missing. README "Regulars" says this to the streamer.
//
// Each Regular has a home building (spread over the map, one per profile below), two hangouts it
// visits in the day, ordinary customer habits, and its own look. Profiles[] is the one place to
// change them; the ids ("fridge_regular_01" ...) are save data and must never change.

using System;
using MelonLoader;
using S1API.Economy;
using S1API.Entities;
using S1API.Entities.Appearances.AccessoryFields;
using S1API.Entities.Appearances.BodyLayerFields;
using S1API.Entities.Appearances.CustomizationFields;
using S1API.Entities.Appearances.FaceLayerFields;
using S1API.GameTime;
using S1API.Map;
using S1API.Map.Buildings;
using S1API.Products;
using S1API.Properties;
using UnityEngine;

[assembly: MelonInfo(typeof(FridgeRegulars.RegularsMod), "FridgeRegulars", "0.1.0", "sensokasucks",
    "https://github.com/sensokasucks/flavr-game-plugins/tree/main/fridge-schedule1")]
[assembly: MelonGame("TVGS", "Schedule I")]

namespace FridgeRegulars
{
    /// <summary>Only here so MelonLoader loads this DLL; S1API finds the Regular classes by itself.</summary>
    public sealed class RegularsMod : MelonMod
    {
        public override void OnInitializeMelon() =>
            LoggerInstance.Msg($"{Profiles.All.Length} regular customers for chatters (needs S1API)");
    }

    /// <summary>How one Regular lives and looks. Building fields are S1API building types.</summary>
    internal sealed class Profile
    {
        public Func<Building> Home, HangoutA, HangoutB;
        public float Gender;              // 0 = male .. 1 = female
        public Color32 Skin;
        public string Hair;               // HairStyle.*
        public Color HairColor;
        public string Shirt;              // Shirts.*
        public Color ShirtColor;
        public string Pants;              // Pants.*
        public Color PantsColor;
        public string Shoes;              // Feet.*
        public string Hat;                // Head.* or null
        public string Face;               // Face.*
        public float SpendMin, SpendMax;  // in-game dollars per week
        public CustomerStandard Standard;
        public DrugType Likes, Dislikes;
        public int Offset;                // minutes added to the day plan so they don't all move together
    }

    internal static class Profiles
    {
        // Homes spread over the map; hangouts are public places. Order = Regular 1 .. 10.
        public static readonly Profile[] All =
        {
            P(() => Building.Get<NorthApartments>(), () => Building.Get<BudsBar>(), () => Building.Get<CornerStore>(),
              0f, new Color32(224, 172, 135, 255), HairStyle.BuzzCut, new Color(0.2f, 0.15f, 0.1f),
              Shirts.TShirt, new Color(0.2f, 0.4f, 0.8f), Pants.Jeans, new Color(0.15f, 0.2f, 0.35f), Feet.Sneakers, Head.Cap,
              Face.Neutral, 200, 600, CustomerStandard.VeryLow, DrugType.Marijuana, DrugType.Heroin, 0),
            P(() => Building.Get<ApartmentBuilding>(), () => Building.Get<Arcade>(), () => Building.Get<SlopShop>(),
              1f, new Color32(141, 85, 36, 255), HairStyle.Afro, new Color(0.05f, 0.05f, 0.05f),
              Shirts.VNeck, new Color(0.8f, 0.3f, 0.5f), Pants.Jeans, new Color(0.1f, 0.1f, 0.15f), Feet.Flats, null,
              Face.SlightSmile, 300, 800, CustomerStandard.Low, DrugType.Cocaine, DrugType.Methamphetamine, 15),
            P(() => Building.Get<UpscaleApartments>(), () => Building.Get<Casino>(), () => Building.Get<Cafe>(),
              0f, new Color32(255, 219, 172, 255), HairStyle.LongSlicked, new Color(0.6f, 0.45f, 0.2f),
              Shirts.Buttonup, Color.white, Pants.CargoPants, new Color(0.2f, 0.2f, 0.2f), Feet.DressShoes, Head.Oakleys,
              Face.SmugPout, 800, 1800, CustomerStandard.High, DrugType.Cocaine, DrugType.Marijuana, 30),
            P(() => Building.Get<TallTower>(), () => Building.Get<ChineseRestaurant>(), () => Building.Get<Nightclub>(),
              1f, new Color32(198, 134, 66, 255), HairStyle.MessyBob, new Color(0.5f, 0.1f, 0.1f),
              Shirts.TuckedTShirt, new Color(0.1f, 0.1f, 0.1f), Pants.Jeans, new Color(0.3f, 0.3f, 0.35f), Feet.CombatBoots, null,
              Face.Neutral, 500, 1200, CustomerStandard.Moderate, DrugType.MDMA, DrugType.Heroin, 45),
            P(() => Building.Get<Caravan>(), () => Building.Get<WestGasMart>(), () => Building.Get<BudsBar>(),
              0f, new Color32(234, 192, 134, 255), HairStyle.Receding, new Color(0.4f, 0.35f, 0.3f),
              Shirts.FlannelButtonUp, new Color(0.6f, 0.15f, 0.1f), Pants.Jorts, new Color(0.3f, 0.4f, 0.55f), Feet.Sandals, Head.BucketHat,
              Face.SlightFrown, 150, 450, CustomerStandard.VeryLow, DrugType.Methamphetamine, DrugType.Cocaine, 60),
            P(() => Building.Get<OverpassBuilding>(), () => Building.Get<SlopShop>(), () => Building.Get<Arcade>(),
              1f, new Color32(255, 205, 148, 255), HairStyle.HighBun, new Color(0.9f, 0.8f, 0.5f),
              Shirts.GasStationTShirt, new Color(0.9f, 0.6f, 0.1f), Pants.CargoPants, new Color(0.25f, 0.3f, 0.2f), Feet.Sneakers, null,
              Face.OpenMouthSmile, 250, 700, CustomerStandard.Low, DrugType.Shrooms, DrugType.Methamphetamine, 75),
            P(() => Building.Get<DocksShippingContainer>(), () => Building.Get<FishWarehouse>(), () => Building.Get<TheCrimsonCanary>(),
              0f, new Color32(92, 56, 32, 255), HairStyle.CloseBuzzCut, new Color(0.05f, 0.05f, 0.05f),
              Shirts.Overalls, new Color(0.2f, 0.3f, 0.5f), Pants.Jeans, new Color(0.15f, 0.15f, 0.2f), Feet.CombatBoots, Head.Beanie,
              Face.Agitated, 300, 900, CustomerStandard.Low, DrugType.Heroin, DrugType.MDMA, 90),
            P(() => Building.Get<ShermanHouse>(), () => Building.Get<Supermarket>(), () => Building.Get<Church>(),
              1f, new Color32(241, 194, 125, 255), HairStyle.ShoulderLength, new Color(0.3f, 0.2f, 0.1f),
              Shirts.RolledButtonUp, new Color(0.5f, 0.7f, 0.5f), Pants.Jeans, new Color(0.2f, 0.25f, 0.4f), Feet.Flats, Head.SmallRoundGlasses,
              Face.Smile, 600, 1400, CustomerStandard.Moderate, DrugType.Marijuana, DrugType.Cocaine, 105),
            P(() => Building.Get<KennedyHouse>(), () => Building.Get<Cafe>(), () => Building.Get<Casino>(),
              0f, new Color32(255, 224, 189, 255), HairStyle.SidePartBob, new Color(0.15f, 0.1f, 0.05f),
              Shirts.Buttonup, new Color(0.3f, 0.35f, 0.6f), Pants.CargoPants, new Color(0.35f, 0.3f, 0.25f), Feet.DressShoes, Head.FlatCap,
              Face.NeutralPout, 900, 2000, CustomerStandard.VeryHigh, DrugType.MDMA, DrugType.Methamphetamine, 120),
            P(() => Building.Get<BenjisMotelRoom>(), () => Building.Get<CornerStore>(), () => Building.Get<Nightclub>(),
              1f, new Color32(161, 102, 94, 255), HairStyle.Mohawk, new Color(0.7f, 0.1f, 0.6f),
              Shirts.TShirt, new Color(0.1f, 0.6f, 0.4f), Pants.Jorts, new Color(0.2f, 0.2f, 0.25f), Feet.Sneakers, null,
              Face.Surprised, 200, 650, CustomerStandard.VeryLow, DrugType.Methamphetamine, DrugType.Shrooms, 135),
        };

        private static Profile P(Func<Building> home, Func<Building> a, Func<Building> b, float gender, Color32 skin,
            string hair, Color hairColor, string shirt, Color shirtColor, string pants, Color pantsColor, string shoes,
            string hat, string face, float spendMin, float spendMax, CustomerStandard standard, DrugType likes,
            DrugType dislikes, int offset) => new Profile
        {
            Home = home, HangoutA = a, HangoutB = b, Gender = gender, Skin = skin, Hair = hair, HairColor = hairColor,
            Shirt = shirt, ShirtColor = shirtColor, Pants = pants, PantsColor = pantsColor, Shoes = shoes, Hat = hat,
            Face = face, SpendMin = spendMin, SpendMax = spendMax, Standard = standard, Likes = likes,
            Dislikes = dislikes, Offset = offset,
        };
    }

    /// <summary>What every Regular shares; the ten classes below only say which profile they are.
    /// Abstract, so S1API doesn't try to make an NPC out of it.</summary>
    public abstract class Regular : NPC
    {
        // Somewhere public in Northtown (S1API's own example NPC stands here). Only used until
        // OnCreated moves the Regular to its home's door, or if that door can't be found.
        private static readonly Vector3 FallbackSpawn = new Vector3(-53.57f, 1.065f, 67.80f);

        /// <summary>1..10: which profile, and the number in "Regular N" / "fridge_regular_NN".</summary>
        protected abstract int Number { get; }

        public override bool IsPhysical => true;
        public override bool IsCustomer => true;

        private Profile Me => Profiles.All[Number - 1];

        // Game time as HHMM from minutes after midnight (S1API schedules use HHMM ints).
        private static int Hhmm(int minutes)
        {
            minutes = ((minutes % 1440) + 1440) % 1440;
            return minutes / 60 * 100 + minutes % 60;
        }

        protected override void ConfigurePrefab(NPCPrefabBuilder builder)
        {
            var p = Me;
            int o = p.Offset;
            builder.WithIdentity($"fridge_regular_{Number:00}", "Regular", Number.ToString())
                .WithSpawnPosition(FallbackSpawn)
                .WithAppearanceDefaults(av =>
                {
                    av.Gender = p.Gender;
                    av.Height = 0.95f + (Number % 3) * 0.04f;
                    av.Weight = 0.3f + (Number % 4) * 0.12f;
                    av.SkinColor = p.Skin;
                    av.LeftEyeLidColor = p.Skin;
                    av.RightEyeLidColor = p.Skin;
                    av.EyeBallTint = Color.white;
                    av.PupilDilation = 0.6f;
                    av.HairPath = p.Hair;
                    av.HairColor = p.HairColor;
                    av.WithFaceLayer<Face>(p.Face, Color.black);
                    av.WithBodyLayer<Shirts>(p.Shirt, p.ShirtColor);
                    av.WithBodyLayer<Pants>(p.Pants, p.PantsColor);
                    av.WithAccessoryLayer<Feet>(p.Shoes, Color.black);
                    if (p.Hat != null)
                        av.WithAccessoryLayer<Head>(p.Hat, Color.white);
                })
                .EnsureCustomer()
                .WithCustomerDefaults(cd =>
                {
                    cd.WithSpending(minWeekly: p.SpendMin, maxWeekly: p.SpendMax)
                        .WithOrdersPerWeek(1, 3)
                        .WithPreferredOrderDay((Day)(Number % 7))
                        .WithOrderTime(Hhmm(10 * 60 + o * 2))
                        .WithStandards(p.Standard)
                        .AllowDirectApproach(true)          // walk up and offer a sample, like any customer
                        .GuaranteeFirstSample(true)
                        .WithCallPoliceChance(0.05f)
                        .WithAffinities(new[] { (p.Likes, 0.6f), (p.Dislikes, -0.4f) });
                })
                .WithRelationshipDefaults(r =>
                {
                    r.WithDelta(1.5f)
                        .SetUnlocked(false)
                        .SetUnlockType(NPCRelationship.UnlockType.DirectApproach);
                })
                .WithSchedule(plan =>
                {
                    // Sleep at home 22:00-07:00, then out: vending machine, two hangouts, home for the evening.
                    plan.EnsureDealSignal()
                        .UseVendingMachine(Hhmm(7 * 60 + 30 + o / 3))
                        .StayInBuilding(p.HangoutA(), Hhmm(9 * 60 + o / 3), 150)
                        .StayInBuilding(p.HangoutB(), Hhmm(13 * 60 + 30 + o / 3), 120)
                        .StayInBuilding(p.HangoutA(), Hhmm(17 * 60 + o / 3), 90)
                        .StayInBuilding(p.Home(), Hhmm(22 * 60 + o / 3), 540);
                });
        }

        protected override void OnCreated()
        {
            try
            {
                base.OnCreated();
                Appearance.Build();
                MoveToHomeDoor();
                Schedule.Enable();
            }
            catch (Exception ex)
            {
                MelonLogger.Warning($"[FridgeRegulars] Regular {Number}: {ex.Message}");
            }
        }

        // Start at the front door of this Regular's home instead of FallbackSpawn. The game's
        // building objects only exist once the map is loaded, which it is by OnCreated.
        private void MoveToHomeDoor()
        {
            var home = Me.Home();
            if (home == null)
                return;
            var buildings = UnityEngine.Object.FindObjectsOfType<Il2CppScheduleOne.Map.NPCEnterableBuilding>();
            foreach (var b in buildings)
            {
                if (b == null || b.BuildingName != home.Name || b.Doors == null || b.Doors.Length == 0)
                    continue;
                var door = b.Doors[0];
                if (door != null && door.AccessPoint != null)
                    Position = door.AccessPoint.position;
                return;
            }
        }
    }

    // The ten Regulars. S1API needs one class per NPC; each only says which profile it is.
    public sealed class Regular1 : Regular { protected override int Number => 1; }
    public sealed class Regular2 : Regular { protected override int Number => 2; }
    public sealed class Regular3 : Regular { protected override int Number => 3; }
    public sealed class Regular4 : Regular { protected override int Number => 4; }
    public sealed class Regular5 : Regular { protected override int Number => 5; }
    public sealed class Regular6 : Regular { protected override int Number => 6; }
    public sealed class Regular7 : Regular { protected override int Number => 7; }
    public sealed class Regular8 : Regular { protected override int Number => 8; }
    public sealed class Regular9 : Regular { protected override int Number => 9; }
    public sealed class Regular10 : Regular { protected override int Number => 10; }
}
