# stats.py
from discord import Embed

def build_stats_embed(user, stats: dict) -> Embed:
    embed = Embed(
        title=f"📊 Statistiken für {user.display_name}",
        color=0x3498DB
    )

    # Standardinfos
    embed.add_field(name="🎮 Name (Mention)", value=stats.get("mention", user.mention), inline=True)

    # Sieg & Teilnahme
    wins = stats.get("wins", 0)
    participations = stats.get("participations", 0)
    winrate = f"{(wins / participations * 100):.1f} %" if participations > 0 else "–"

    embed.add_field(name="🏆 Siege", value=wins, inline=True)
    embed.add_field(name="🧩 Teilnahmen", value=participations, inline=True)
    embed.add_field(name="📈 Winrate", value=winrate, inline=True)

    # Lieblingsspiel
    game_stats = stats.get("game_stats", {})
    if game_stats:
        favorite_game = max(game_stats.items(), key=lambda kv: kv[1])
        embed.add_field(
            name="🎮 Lieblingsspiel",
            value=f"{favorite_game[0]} ({favorite_game[1]}x gespielt)",
            inline=False
        )

    embed.set_footer(text="Turnierauswertung")
    return embed

def build_leaderboard_embed(stats_data: dict) -> Embed:
    sorted_players = sorted(stats_data.items(), key=lambda kv: kv[1].get("wins", 0), reverse=True)
    embed = Embed(
        title="🏆 Turnier-Leaderboard",
        description="Top-Spieler nach Anzahl der Siege",
        color=0xF1C40F
    )

    for rank, (user_id, stat) in enumerate(sorted_players[:10], start=1):
        wins = stat.get("wins", 0)
        name = stat.get("name", f"<@{user_id}>")
        embed.add_field(
            name="\u200b",  # unsichtbarer Name
            value=f"**{rank}. {name} – 🏅 {wins} {'Sieg' if wins == 1 else 'Siege'}**",
            inline=False
        )

    embed.set_footer(text="Nur Siege aus abgeschlossenen Turnieren werden gezählt.")
    return embed

def build_global_stats_embed() -> Embed:
    config = load_config()
    embed_config = config.get("GLOBAL_STATS_EMBED", {})

    data = load_global_data()
    stats = data.get("player_stats", {})
    total_players = len(stats)
    total_wins = sum(player.get("wins", 0) for player in stats.values())

    # Bester Spieler
    best_player = max(stats.items(), key=lambda kv: kv[1].get("wins", 0), default=None)
    best_name = best_player[1]["name"] if best_player else "Niemand"
    best_wins = best_player[1]["wins"] if best_player else 0

    # Beliebtestes Spiel (nur wenn gespeichert)
    game_counter = Counter()
    for game in data.get("game_votes", []):
        game_counter[game] += 1
    if game_counter:
        most_played_game, count = game_counter.most_common(1)[0]
        game_text = f"{most_played_game} ({count}x)"
    else:
        game_text = "Noch keine Spielstatistiken."

    # Embed bauen
    embed = Embed(
        title=embed_config.get("title", "📊 Turnier-Übersicht"),
        description=embed_config.get("description", ""),
        color=0x1ABC9C
    )
    embed.add_field(name="👥 Spieler insgesamt", value=str(total_players), inline=True)
    embed.add_field(name="🏆 Vergebene Siege", value=str(total_wins), inline=True)
    embed.add_field(name="🥇 Bester Spieler", value=f"{best_name} ({best_wins} Siege)", inline=False)
    embed.add_field(name="🔥 Beliebtestes Spiel", value=game_text, inline=False)

    footer = embed_config.get("footer")
    if footer:
        embed.set_footer(text=footer)

    return embedc