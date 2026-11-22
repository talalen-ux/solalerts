"""Club badges drawn from club colours: (three-letter code, primary colour, secondary colour).

These are original monogram badges, not the clubs' crests (which are trademarks and cannot be
loaded by the card page anyway). Teams missing here fall back to a neutral badge in the template.
"""

BADGES = {
    # Premier League
    "AFC Bournemouth": ("BOU", "#d71920", "#000000"), "Arsenal FC": ("ARS", "#ef0107", "#ffffff"),
    "Aston Villa FC": ("AVL", "#670e36", "#95bfe5"), "Brentford FC": ("BRE", "#e30613", "#ffffff"),
    "Brighton & Hove Albion FC": ("BHA", "#0057b8", "#ffffff"), "Chelsea FC": ("CHE", "#034694", "#ffffff"),
    "Coventry City FC": ("COV", "#6cace4", "#ffffff"), "Crystal Palace FC": ("CRY", "#1b458f", "#c4122e"),
    "Everton FC": ("EVE", "#003399", "#ffffff"), "Fulham FC": ("FUL", "#ffffff", "#000000"),
    "Hull City AFC": ("HUL", "#f5a12d", "#000000"), "Ipswich Town FC": ("IPS", "#0044a9", "#ffffff"),
    "Leeds United FC": ("LEE", "#ffffff", "#1d428a"), "Liverpool FC": ("LIV", "#c8102e", "#ffffff"),
    "Manchester City FC": ("MCI", "#6cabdd", "#ffffff"), "Manchester United FC": ("MUN", "#da291c", "#fbe122"),
    "Newcastle United FC": ("NEW", "#241f20", "#ffffff"), "Nottingham Forest FC": ("NFO", "#dd0000", "#ffffff"),
    "Sunderland AFC": ("SUN", "#eb172b", "#ffffff"), "Tottenham Hotspur FC": ("TOT", "#ffffff", "#132257"),
    # La Liga
    "Athletic Club": ("ATH", "#ee2523", "#ffffff"), "CA Osasuna": ("OSA", "#d91a21", "#0a346f"),
    "Club Atlético de Madrid": ("ATM", "#cb3524", "#272e61"), "Deportivo Alavés": ("ALA", "#0761af", "#ffffff"),
    "Elche CF": ("ELC", "#05642c", "#ffffff"), "FC Barcelona": ("BAR", "#a50044", "#004d98"),
    "Getafe CF": ("GET", "#005999", "#ffffff"), "Levante UD": ("LEV", "#b4053f", "#004b9a"),
    "Málaga CF": ("MAL", "#0b6fb5", "#ffffff"), "RC Celta de Vigo": ("CEL", "#8ac3ee", "#ffffff"),
    "RC Deportivo La Coruña": ("DEP", "#0066b3", "#ffffff"), "RCD Espanyol de Barcelona": ("ESP", "#007fc8", "#ffffff"),
    "Rayo Vallecano de Madrid": ("RAY", "#ffffff", "#e53027"), "Real Betis Balompié": ("BET", "#0bb363", "#ffffff"),
    "Real Madrid CF": ("RMA", "#ffffff", "#febe10"), "Real Racing Club de Santander": ("RAC", "#00813c", "#ffffff"),
    "Real Sociedad de Fútbol": ("RSO", "#0067b1", "#ffffff"), "Sevilla FC": ("SEV", "#ffffff", "#d4021d"),
    "Valencia CF": ("VAL", "#ffffff", "#ee3524"), "Villarreal CF": ("VIL", "#ffe667", "#005187"),
    # Serie A
    "AC Milan": ("MIL", "#fb090b", "#000000"), "AC Monza": ("MON", "#e30613", "#ffffff"),
    "ACF Fiorentina": ("FIO", "#482e92", "#ffffff"), "AS Roma": ("ROM", "#8e1f2f", "#f0bc42"),
    "Atalanta BC": ("ATA", "#1e71b8", "#000000"), "Bologna FC 1909": ("BOL", "#1a2f48", "#a21c26"),
    "Cagliari Calcio": ("CAG", "#002350", "#a51e36"), "Como 1907": ("COM", "#003df5", "#ffffff"),
    "FC Internazionale Milano": ("INT", "#0068a8", "#000000"), "Frosinone Calcio": ("FRO", "#fcd116", "#0047ab"),
    "Genoa CFC": ("GEN", "#a51e36", "#002350"), "Juventus FC": ("JUV", "#000000", "#ffffff"),
    "Parma Calcio 1913": ("PAR", "#ffd200", "#1b4094"), "SS Lazio": ("LAZ", "#87d8f7", "#ffffff"),
    "SSC Napoli": ("NAP", "#12a0d7", "#ffffff"), "Torino FC": ("TOR", "#881f19", "#ffffff"),
    "US Lecce": ("LEC", "#ffdd00", "#d71920"), "US Sassuolo Calcio": ("SAS", "#00a752", "#000000"),
    "Udinese Calcio": ("UDI", "#000000", "#ffffff"), "Venezia FC": ("VEN", "#000000", "#f47a20"),
    # Bundesliga
    "1. FC Köln": ("KOE", "#ed1c24", "#ffffff"), "1. FC Union Berlin": ("FCU", "#eb1923", "#ffffff"),
    "1. FSV Mainz 05": ("M05", "#c3141e", "#ffffff"), "Bayer 04 Leverkusen": ("B04", "#e32221", "#000000"),
    "Borussia Dortmund": ("BVB", "#fde100", "#000000"), "Borussia Mönchengladbach": ("BMG", "#000000", "#ffffff"),
    "Eintracht Frankfurt": ("SGE", "#e1000f", "#000000"), "FC Augsburg": ("FCA", "#ba3733", "#46714d"),
    "FC Bayern München": ("FCB", "#dc052d", "#0066b2"), "FC Schalke 04": ("S04", "#004d9d", "#ffffff"),
    "Hamburger SV": ("HSV", "#0a3f86", "#ffffff"), "RB Leipzig": ("RBL", "#dd0741", "#ffffff"),
    "SC Freiburg": ("SCF", "#000000", "#e2001a"), "SC Paderborn 07": ("SCP", "#005ca9", "#000000"),
    "SV 07 Elversberg": ("SVE", "#000000", "#ffffff"), "SV Werder Bremen": ("SVW", "#1d9053", "#ffffff"),
    "TSG 1899 Hoffenheim": ("TSG", "#1961b5", "#ffffff"), "VfB Stuttgart": ("VFB", "#ffffff", "#e32219"),
    # Ligue 1
    "AJ Auxerre": ("AJA", "#ffffff", "#0b67b2"), "AS Monaco FC": ("ASM", "#e2001a", "#ffffff"),
    "Angers SCO": ("SCO", "#000000", "#ffffff"), "ES Troyes AC": ("ETR", "#005ba4", "#ffffff"),
    "FC Lorient": ("FCL", "#f37021", "#000000"), "Le Havre AC": ("HAC", "#7ec0ee", "#002c5f"),
    "Le Mans FC": ("LMF", "#e2001a", "#fcd116"), "Lille OSC": ("LIL", "#e01e13", "#20325f"),
    "OGC Nice": ("NIC", "#c8102e", "#000000"), "Olympique Lyonnais": ("OL", "#ffffff", "#14387f"),
    "Olympique de Marseille": ("OM", "#2faee0", "#ffffff"), "Paris FC": ("PFC", "#1b2a4e", "#d7b46a"),
    "Paris Saint-Germain FC": ("PSG", "#004170", "#da291c"), "RC Strasbourg Alsace": ("RCS", "#009fe3", "#ffffff"),
    "Racing Club de Lens": ("RCL", "#ffe500", "#e10600"), "Stade Brestois 29": ("SB29", "#e30613", "#ffffff"),
    "Stade Rennais FC 1901": ("SRF", "#e13327", "#000000"), "Toulouse FC": ("TFC", "#6f2c91", "#ffffff"),
}

# League marks: (short label, background, foreground)
LEAGUE_MARKS = {
    "EPL": ("PL", "#3d195b", "#00ff85"), "LALIGA": ("LL", "#ff4b44", "#ffffff"),
    "SERIEA": ("SA", "#0b1f4d", "#22c4ff"), "BUNDESLIGA": ("BL", "#d20515", "#ffffff"),
    "LIGUE1": ("L1", "#091c3e", "#dae025"),
}


def for_teams(teams) -> dict:
    return {t: BADGES[t] for t in teams if t in BADGES}
