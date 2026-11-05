"""Approximate stadium coordinates (lat, lon) and travel distance between clubs."""

from __future__ import annotations

import math

COORDS = {
    # England
    "AFC Bournemouth": (50.735, -1.838), "Arsenal FC": (51.555, -0.108), "Aston Villa FC": (52.509, -1.885),
    "Brentford FC": (51.491, -0.289), "Brighton & Hove Albion FC": (50.862, -0.083), "Burnley FC": (53.789, -2.230),
    "Chelsea FC": (51.482, -0.191), "Coventry City FC": (52.448, -1.496), "Crystal Palace FC": (51.398, -0.086),
    "Everton FC": (53.425, -3.003), "Fulham FC": (51.475, -0.222), "Hull City AFC": (53.746, -0.368),
    "Ipswich Town FC": (52.055, 1.145), "Leeds United FC": (53.778, -1.572), "Leicester City FC": (52.620, -1.142),
    "Liverpool FC": (53.431, -2.961), "Luton Town FC": (51.884, -0.432), "Manchester City FC": (53.483, -2.200),
    "Manchester United FC": (53.463, -2.291), "Newcastle United FC": (54.976, -1.622),
    "Nottingham Forest FC": (52.940, -1.133), "Sheffield United FC": (53.370, -1.471),
    "Southampton FC": (50.906, -1.391), "Sunderland AFC": (54.915, -1.388), "Tottenham Hotspur FC": (51.604, -0.066),
    "West Ham United FC": (51.539, -0.017), "Wolverhampton Wanderers FC": (52.590, -2.130),
    # Spain
    "Athletic Club": (43.264, -2.950), "CA Osasuna": (42.797, -1.637), "CD Leganés": (40.340, -3.760),
    "Club Atlético de Madrid": (40.436, -3.599), "Cádiz CF": (36.503, -6.273), "Deportivo Alavés": (42.837, -2.688),
    "Elche CF": (38.267, -0.663), "FC Barcelona": (41.381, 2.123), "Getafe CF": (40.326, -3.715),
    "Girona FC": (41.961, 2.829), "Granada CF": (37.153, -3.596), "Levante UD": (39.495, -0.364),
    "Málaga CF": (36.734, -4.426), "RC Celta de Vigo": (42.212, -8.740), "RC Deportivo La Coruña": (43.369, -8.417),
    "RCD Espanyol de Barcelona": (41.348, 2.076), "RCD Mallorca": (39.590, 2.630),
    "Rayo Vallecano de Madrid": (40.392, -3.659), "Real Betis Balompié": (37.357, -5.982),
    "Real Madrid CF": (40.453, -3.688), "Real Oviedo": (43.361, -5.870),
    "Real Racing Club de Santander": (43.476, -3.794), "Real Sociedad de Fútbol": (43.301, -1.974),
    "Real Valladolid CF": (41.645, -4.761), "Sevilla FC": (37.384, -5.971), "UD Almería": (36.840, -2.435),
    "UD Las Palmas": (28.100, -15.457), "Valencia CF": (39.475, -0.358), "Villarreal CF": (39.944, -0.104),
    # Italy
    "AC Milan": (45.478, 9.124), "AC Monza": (45.583, 9.308), "AC Pisa 1909": (43.719, 10.408),
    "ACF Fiorentina": (43.781, 11.282), "AS Roma": (41.934, 12.455), "Atalanta BC": (45.709, 9.681),
    "Bologna FC 1909": (44.492, 11.310), "Cagliari Calcio": (39.200, 9.137), "Como 1907": (45.814, 9.072),
    "Empoli FC": (43.726, 10.955), "FC Internazionale Milano": (45.478, 9.124), "Frosinone Calcio": (41.635, 13.323),
    "Genoa CFC": (44.416, 8.952), "Hellas Verona FC": (45.435, 10.969), "Juventus FC": (45.110, 7.641),
    "Parma Calcio 1913": (44.795, 10.338), "SS Lazio": (41.934, 12.455), "SSC Napoli": (40.828, 14.193),
    "Torino FC": (45.042, 7.650), "US Cremonese": (45.142, 10.031), "US Lecce": (40.365, 18.209),
    "US Salernitana 1919": (40.646, 14.824), "US Sassuolo Calcio": (44.715, 10.649), "Udinese Calcio": (46.082, 13.200),
    "Venezia FC": (45.428, 12.364),
    # Germany
    "1. FC Heidenheim 1846": (48.669, 10.139), "1. FC Köln": (50.934, 6.875), "1. FC Union Berlin": (52.457, 13.568),
    "1. FSV Mainz 05": (49.984, 8.224), "Bayer 04 Leverkusen": (51.038, 7.002), "Borussia Dortmund": (51.493, 7.452),
    "Borussia Mönchengladbach": (51.175, 6.385), "Eintracht Frankfurt": (50.069, 8.646), "FC Augsburg": (48.323, 10.886),
    "FC Bayern München": (48.219, 11.625), "FC Schalke 04": (51.555, 7.068), "FC St. Pauli 1910": (53.555, 9.968),
    "Hamburger SV": (53.587, 9.899), "Holstein Kiel": (54.349, 10.124), "RB Leipzig": (51.346, 12.348),
    "SC Freiburg": (48.022, 7.830), "SC Paderborn 07": (51.731, 8.711), "SV 07 Elversberg": (49.327, 7.124),
    "SV Darmstadt 98": (49.858, 8.673), "SV Werder Bremen": (53.067, 8.838), "TSG 1899 Hoffenheim": (49.238, 8.888),
    "VfB Stuttgart": (48.792, 9.232), "VfL Bochum 1848": (51.490, 7.237), "VfL Wolfsburg": (52.432, 10.804),
    # France
    "AJ Auxerre": (47.787, 3.589), "AS Monaco FC": (43.728, 7.416), "AS Saint-Étienne": (45.461, 4.390),
    "Angers SCO": (47.460, -0.531), "Clermont Foot 63": (45.816, 3.122), "ES Troyes AC": (48.308, 4.099),
    "FC Lorient": (47.749, -3.369), "FC Metz": (49.110, 6.160), "FC Nantes": (47.256, -1.525),
    "Le Havre AC": (49.499, 0.170), "Le Mans FC": (47.959, 0.224), "Lille OSC": (50.612, 3.130),
    "Montpellier HSC": (43.622, 3.812), "OGC Nice": (43.705, 7.193), "Olympique Lyonnais": (45.765, 4.982),
    "Olympique de Marseille": (43.270, 5.396), "Paris FC": (48.841, 2.253), "Paris Saint-Germain FC": (48.841, 2.253),
    "RC Strasbourg Alsace": (48.560, 7.755), "Racing Club de Lens": (50.433, 2.815), "Stade Brestois 29": (48.403, -4.462),
    "Stade Rennais FC 1901": (48.108, -1.713), "Stade de Reims": (49.247, 4.025), "Toulouse FC": (43.583, 1.434),
}


def distance_km(a: str, b: str) -> float | None:
    if a not in COORDS or b not in COORDS:
        return None
    (la1, lo1), (la2, lo2) = (map(math.radians, COORDS[a]), map(math.radians, COORDS[b]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))
