import os
from datetime import datetime,timedelta
import chess
import chess.pgn
from stockfish import Stockfish
import io
import csv
import numpy as np
from scipy.interpolate import make_interp_spline
import matplotlib.pyplot as plt
import requests
from dataclasses import dataclass
import seaborn as sns
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import os

def send_email(sender_email, sender_password, recipient_email, subject, body, attachment_path):
    try:
        # Creating the message
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient_email
        msg['Subject'] = subject

        # Adding body
        msg.attach(MIMEText(body, 'plain'))

        # Adding the attachment
        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, 'rb') as attachment_file:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment_file.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename={os.path.basename(attachment_path)}',
                )
                msg.attach(part)

        # Connecting to Gmail server
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)

        # Sending the message
        text = msg.as_string()
        server.sendmail(sender_email, recipient_email, text)
        server.quit()

        print("Email sent successfully!")

    except Exception as e:
        print(f"Failed to send email: {e}")



# for storing player data
@dataclass
class Player:
    color: str
    blunders: int = 0
    mistakes: int = 0
    inaccuracies: int = 0
    loss: float = 0.0

@dataclass
class GameStats:
    muchWorse: int = 0
    slightWorse: int = 0
    similar: int = 0
    slightBetter: int = 0
    muchBetter: int = 0
    gamesWon = []
    gamesLost =[]
    gamesDrawn: int = 0
    opponentsRankingHistory = []
    playerRankingHistory = []

def save_games_to_pgn(games, filename):
    with open(filename, "w") as pgn_file:
        for game in games:
            exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
            pgn_file.write(game.accept(exporter))
            pgn_file.write("\n\n")

# checking if the game has been played this week or this day
def is_recent_game(game_date_str,weeklyRaport):
    if weeklyRaport:
        one_week_ago = datetime.now() - timedelta(weeks=1)
        game_date = datetime.strptime(game_date_str, "%Y.%m.%d")
        return game_date >= one_week_ago
    else:
        one_day_ago = datetime.now() - timedelta(days=1)
        game_date = datetime.strptime(game_date_str, "%Y.%m.%d")
        return game_date >= one_day_ago

def getRecentGames(TOKEN, API_URL, username, today,weeklyRaport):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = requests.get(
        API_URL,
        params={"max": 300},
        headers=headers,
        stream=True
    )
    response.raise_for_status()

    games = []
    buffer = ""
    empty_line_count = 0

    for chunk in response.iter_lines(decode_unicode=True):
        chunk = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk

        if chunk.strip() == "":
            empty_line_count += 1
            if empty_line_count == 2:
                pgn_io = io.StringIO(buffer)
                game = chess.pgn.read_game(pgn_io)

                if game is None:
                    continue

                game_date_str = game.headers.get("Date")
                if game_date_str and not is_recent_game(game_date_str,weeklyRaport):
                    print("Stopping analysis.")
                    save_games_to_pgn(games, f"games_{username}_{today}.pgn")
                    return games

                games.append(game)
                buffer = ""
                empty_line_count = 0  #
            continue

        empty_line_count = 0
        buffer += chunk + "\n"

    if buffer.strip():
        pgn_io = io.StringIO(buffer)
        game = chess.pgn.read_game(pgn_io)
        if game:
            games.append(game)
    save_games_to_pgn(games, f"games_{username}_{today}.pgn")
    return games


# function for analyzing the single game with given parameters
def analyzeGame(game, drawChart,depth,username,gameNum,totalGames,gamestats):
    stockfish_path = "C:\\Users\\Radek\\Downloads\\stockfish-windows-x86-64-avx2\\stockfish\\stockfish-windows-x86-64-avx2.exe"
    stockfish = Stockfish(path=stockfish_path)
    stockfish.set_depth(depth)

    board = game.board()

    # checking what color is the player
    user_color = None
    if game.headers.get("White") == username:
        user_color = "white"
        gamestats.playerRankingHistory.append(int(game.headers.get("WhiteElo")))
        gamestats.opponentsRankingHistory.append(int(game.headers.get("BlackElo")))
        if game.headers.get("Result") == "1-0":
            gamestats.gamesWon.append(game.headers.get("Termination"))
        elif game.headers.get("Result") == "1/2-1/2":
            gamestats.gamesDrawn += 1
        else:
            gamestats.gamesLost.append(game.headers.get("Termination"))
    else:
        user_color = "black"
        gamestats.playerRankingHistory.append(int(game.headers.get("BlackElo")))
        gamestats.opponentsRankingHistory.append(int(game.headers.get("WhiteElo")))
        if game.headers.get("Result") == "0-1":
            gamestats.gamesWon.append(game.headers.get("Termination"))
        elif game.headers.get("Result") == "1/2-1/2":
            gamestats.gamesDrawn += 1
        else:
            gamestats.gamesLost.append(game.headers.get("Termination"))

    # Creating CSV file
    csv_file = "game_analysis.csv"
    with open(csv_file, mode="w", newline="") as file:
        csv_writer = csv.writer(file)
        csv_writer.writerow(["Move", "Evaluation (centipawns)"])  # Headers
        evaluations = []
        moves = []
        move_number = 1
        endFlag = False
        moves = list(game.mainline_moves())
        num_moves = len(moves)
        blackPlayer=Player("black")
        whitePlayer=Player("white")
        for move in game.mainline_moves():

            progress = (gameNum-1+(move_number / num_moves))/totalGames*100
            print(f"\rProgress: {progress:.2f}%", end="")
            board.push(move)
            stockfish.set_fen_position(board.fen())
            evaluation = stockfish.get_evaluation()

            # Processing the evaluation
            if evaluation["type"] == "cp":
                value = evaluation["value"]
            elif evaluation["type"] == "mate":
                if evaluation["value"] > 0:
                    value = 2000
                elif evaluation["value"] < 0:
                    value = -2000
                else:
                    endFlag = True
            else:
                value = 0

            # Saving to CSV file
            if not endFlag:
                csv_writer.writerow([f"{move_number}. {move}", value / 100])

            # Data for the chart
            moves.append(f"{move_number}. {move}")
            evaluations.append(value / 100)

            if move_number % 2 == 0:
                loss = abs(evaluations[-2] - (value / 100))
                blackPlayer.loss += loss
                if loss > 3:
                    blackPlayer.blunders += 1
                elif loss > 1.5:
                    blackPlayer.mistakes += 1
                elif loss > 0.5:
                    blackPlayer.inaccuracies += 1

            elif move_number % 2 == 1 and move_number > 1:
                loss = abs(evaluations[-2] - (value / 100))
                whitePlayer.loss += loss
                if loss > 3:
                    whitePlayer.blunders += 1
                elif loss > 1.5:
                    whitePlayer.mistakes += 1
                elif loss > 0.5:
                    whitePlayer.inaccuracies += 1
            move_number += 1

    if drawChart == True:
        # Creating additional data for smoother graph
        x = np.arange(1, len(evaluations) + 1)
        y = np.array(evaluations)

        # Interpolation
        x_new = np.linspace(x.min(), x.max(), len(evaluations) * 20)
        spline = make_interp_spline(x, y, k=1)
        y_smooth = spline(x_new)


        # Chart
        plt.figure(figsize=(10, 6))
        plt.plot(x_new, y_smooth, color="blue", label="Evaluation")
        plt.gca().set_facecolor("grey")
        plt.fill_between(x_new, y_smooth, 0, where=(y_smooth >= 0), color="white", alpha=0.3)
        plt.fill_between(x_new, y_smooth, 0, where=(y_smooth < 0), color="black", alpha=0.6)
        plt.axhline(0, color="black", linestyle="-", linewidth=2)
        plt.title("Game review", fontsize=14)
        plt.xlabel("Move", fontsize=12)
        plt.ylabel("Eval", fontsize=12)
        plt.grid(True, alpha=0.5)
        plt.tight_layout()
        plt.show()

        print(
            f"\nWhite avg centipawn loss: {int(abs(200 * whitePlayer.loss / len(evaluations)))}\t Blunders:{whitePlayer.blunders}\t Mistakes:{whitePlayer.mistakes}\t Inaccuracies: {whitePlayer.inaccuracies}\n Black avg centipawn loss: {int(abs(200 * blackPlayer.loss / len(evaluations)))}:.2f\t Blunders: {blackPlayer.blunders}\t Mistakes: {blackPlayer.mistakes}\t Inaccuracies: {blackPlayer.inaccuracies}\n")
    if user_color=="white":
        return whitePlayer,blackPlayer
    else:
        return blackPlayer,whitePlayer


################################
################################ The program
################################
def mainFunction():

    today = datetime.now().date()

    print("Incredible chess analyzer v 1.0 by Radosław Tonga\n")

    usercheck = input("Do you want to see an example analisys or have neccesary data for your own analisys? (Lichess token and username)\n1. See example analisys\t 2. I have valid credentials\n")

    username="Radek03"
    TOKEN = "lip_CYH34FOuKQ3R5vNzcyux"

    if usercheck == "2":

        username=input("Enter your username: \n")
        TOKEN=input("Enter your token: \n")
    print("Proceeding with analisys...\n")
    API_URL = f"https://lichess.org/api/games/user/{username}"

    file_path = f"games_{username}_{today}.pgn"
    if not os.path.exists(file_path):



        # Pobierz dane partii
        response = requests.get(API_URL, headers={"Authorization": f"Bearer {TOKEN}"})
        if response.status_code == 200:
            with open(f"games_{username}.pgn", "w", encoding="utf-8") as file:
                file.write(response.text)
            print(f"Zapisano partie do pliku 'games_{username}_{today}.pgn'.")
        else:
            print(f"Błąd: {response.status_code}")


    games = []
    playerLossList = []
    opponentLossList = []
    gameStats = GameStats()
    numGames=int(input("How many games do you want to analyze?\n"))
    userTimeControl = int(input("What time control do you want the analysed games to be?\n1.Bullet\t\t 2.Blitz\t\t 3.Rapid\t\t 4.Classical\n"))
    depth = int(input("What depth of analysis do you want to have? (1-20)\n"))
    with open(file_path, "r", encoding="utf-8") as pgn_file:
        aPlayer = Player("white")
        bPlayer = Player("black")
        nr=0
        while nr < numGames and chess.pgn.read_game(pgn_file) is not None:
            game = chess.pgn.read_game(pgn_file)

            start, increment = map(int, game.headers.get("TimeControl").split("+"))
            if start + (increment * 60)<180:
                gameTimeControl = 1
            elif start + (increment * 60)<600:
                gameTimeControl = 2
            elif start + (increment * 60)<3600:
                gameTimeControl = 3
            else:
                gameTimeControl = 4


            if gameTimeControl == userTimeControl:
                nr+=1
                player,opponent = analyzeGame(game,False,depth,username,nr, numGames,gameStats)
                aPlayer.loss += player.loss
                aPlayer.blunders += player.blunders
                aPlayer.mistakes += player.mistakes
                aPlayer.inaccuracies += player.inaccuracies
                bPlayer.loss += opponent.loss
                bPlayer.blunders += opponent.blunders
                bPlayer.mistakes += opponent.mistakes
                bPlayer.inaccuracies += opponent.inaccuracies

                playerLossList.append(player.loss)
                opponentLossList.append(opponent.loss)

                difference = player.loss-opponent.loss
                if difference > 10:
                    gameStats.muchWorse+=1
                elif difference > 5:
                    gameStats.slightWorse+=1
                elif difference > -5:
                    gameStats.similar+=1
                elif difference > -10:
                    gameStats.slightBetter+=1
                else:
                    gameStats.muchBetter+=1


    if numGames>0:
        aPlayer.loss/=numGames
        aPlayer.mistakes/=numGames
        aPlayer.inaccuracies/=numGames
        aPlayer.blunders/=numGames
        bPlayer.loss/=numGames
        bPlayer.mistakes/=numGames
        bPlayer.inaccuracies/=numGames
        bPlayer.blunders/=numGames

        playerPerformance = int(sum(gameStats.opponentsRankingHistory)/numGames * (0.5+(gameStats.gamesDrawn*0.5+len(gameStats.gamesWon))/numGames))
        games = []
        for num in range(nr):
            games.append(num+1)

        # Chart
        plt.figure(figsize=(10, 6))
        plt.bar(games, opponentLossList, color="red", label="Opponent Loss",alpha=0.5)
        plt.bar(games, playerLossList, color="blue", label="Player Loss",alpha=0.5)
        plt.gca().set_facecolor("grey")
        plt.title("Player vs Opponents comparison", fontsize=14)
        plt.xlabel("Game", fontsize=12)
        plt.ylabel("Loss", fontsize=12)
        plt.grid(True, alpha=0.5)
        plt.tight_layout()
        plt.show()



        # Chart
        plt.figure(figsize=(10, 6))
        plt.plot(games,gameStats.playerRankingHistory, color="green", label="Player rating",alpha=0.5)
        plt.gca().set_facecolor("grey")
        plt.title("Player rating chart", fontsize=14)
        plt.xlabel("Game", fontsize=12)
        plt.ylabel("Rating", fontsize=12)
        plt.grid(True, alpha=0.5)
        plt.tight_layout()
        plt.show()


        print(f"\nPlayer average loss: {round(aPlayer.loss)},Opponent average loss: {round(bPlayer.loss)}\n")
        print(f"Games statistics: ")
        print(f'\033[38;2;0;255;0m')
        print(f"Games played much better that your opponent:{gameStats.muchBetter} ")
        print(f'\033[38;2;125;255;0m')
        print(f"Games played better than your opponent:{gameStats.slightBetter} ")
        print(f'\033[38;2;255;255;0m')
        print(f"Games played similarly to your opponent: {gameStats.similar} ")
        print(f'\033[38;2;255;125;0m')
        print(f"Games played worse than your opponent:{gameStats.slightWorse} ")
        print(f'\033[38;2;255;0;0m')
        print(f"Games played much worse than your opponent:{gameStats.muchWorse} ")
        print(f'\033[38;2;255;255;255m')
        print(f"\nPlayer ranking performance over the last {numGames} games: {playerPerformance}\n")



        if aPlayer.loss<bPlayer.loss:
            print("Good job! You are often better that your opponents.")
        else:
            print("It's jOver")


###################################################
###################################################
################################################### RAPORT
###################################################
###################################################

def generateRaport(send):
    today = datetime.now().date()
    weeklyRaport = False
    if today.weekday() == "Sunday":
        weeklyRaport = True
    print("Incredible chess analyzer v 1.0 by Radosław Tonga\n")
    username = "Radek03"
    TOKEN = "lip_CYH34FOuKQ3R5vNzcyux"

    print("Proceeding with analisys...\n")
    API_URL = f"https://lichess.org/api/games/user/{username}"

    file_path = f"games_{username}_{today}.pgn"



    if not os.path.exists(file_path) or not weeklyRaport:
        getRecentGames(TOKEN, API_URL,username,today,weeklyRaport)


    timeControls = ["bullet","blitz","rapid","classical"]
    for userTimeControl in range(0, 4):
        print(f"Analisyng for {timeControls[userTimeControl]}")
        playerLossList = []
        opponentLossList = []
        gameStats = GameStats()
        aPlayer = Player("white")
        bPlayer = Player("black")

        with open(file_path, 'r') as file:
            line_count = sum(1 for _ in file)

        approxGames = line_count/25

        with open(file_path, "r", encoding="utf-8") as pgn_file:

            nr = 0

            game = chess.pgn.read_game(pgn_file)
            while game is not None and type(game.headers.get("TimeControl")) is not type(None):
                start, increment = map(int, game.headers.get("TimeControl").split("+"))
                if start + (increment * 60) < 180:
                    gameTimeControl = 0
                elif start + (increment * 60) < 600:
                    gameTimeControl = 1
                elif start + (increment * 60) < 3600:
                    gameTimeControl = 2
                else:
                    gameTimeControl = 3

                if gameTimeControl == userTimeControl:
                    nr += 1
                    player, opponent = analyzeGame(game, False, 10, username, nr, approxGames, gameStats)
                    aPlayer.loss += player.loss
                    aPlayer.blunders += player.blunders
                    aPlayer.mistakes += player.mistakes
                    aPlayer.inaccuracies += player.inaccuracies
                    bPlayer.loss += opponent.loss
                    bPlayer.blunders += opponent.blunders
                    bPlayer.mistakes += opponent.mistakes
                    bPlayer.inaccuracies += opponent.inaccuracies

                    playerLossList.append(player.loss)
                    opponentLossList.append(opponent.loss)

                    difference = player.loss - opponent.loss
                    if difference > 10:
                        gameStats.muchWorse += 1
                    elif difference > 5:
                        gameStats.slightWorse += 1
                    elif difference > -5:
                        gameStats.similar += 1
                    elif difference > -10:
                        gameStats.slightBetter += 1
                    else:
                        gameStats.muchBetter += 1
                game = chess.pgn.read_game(pgn_file)

            if nr > 0:
                aPlayer.loss /= nr
                aPlayer.mistakes /= nr
                aPlayer.inaccuracies /= nr
                aPlayer.blunders /= nr
                bPlayer.loss /= nr
                bPlayer.mistakes /= nr
                bPlayer.inaccuracies /= nr
                bPlayer.blunders /= nr

                playerPerformance = int(sum(gameStats.opponentsRankingHistory) / nr * (
                            0.5 + (gameStats.gamesDrawn * 0.5 + len(gameStats.gamesWon)) / nr))
                games = []
                for num in range(nr):
                    games.append(num + 1)

        if nr>0:

            # General plot styling
            sns.set_theme(style="darkgrid")  # Use Seaborn style for a modern look

            # Colors and custom palette
            player_color = "#1f77b4"  # Blue for the player
            opponent_color = "#ff7f0e"  # Orange for the opponent
            rating_color = "#2ca02c"  # Green for ratings
            background_color = "#3b3b3b"  # Dark background
            text_color = "#e5e5e5"  # Light text

            # Figure and axes
            fig, axes = plt.subplots(5, 1, figsize=(12, 24), gridspec_kw={'height_ratios': [1, 1,1,1, 1]})
            fig.patch.set_facecolor(background_color)  # Set background for the entire figure

            if weeklyRaport:
                period = f"{(datetime.now() - timedelta(weeks=1)).date()}  -  {today}"
            else:
                period = f"{(datetime.now() - timedelta(days=1)).date()}  -  {today}"
            fig.suptitle(f"Report for time control: {timeControls[userTimeControl]} for player {username}\n {period}",
                         fontsize=18, fontweight='bold', color=text_color)
            # Chart 1: Player vs Opponent Loss Comparison
            axes[0].bar(games, opponentLossList, color=opponent_color, label="Opponent Loss", alpha=0.8)
            axes[0].bar(games, playerLossList, color=player_color, label="Player Loss", alapha=0.8)
            axes[0].set_facecolor(background_color)
            axes[0].set_title("Player vs Opponent Loss Comparison", fontsize=14, color=text_color)
            axes[0].set_xlabel("Game", fontsize=12, color=text_color)
            axes[0].set_ylabel("Loss", fontsize=12, color=text_color)
            axes[0].grid(color="white", linestyle="--", alpha=0.2)
            axes[0].tick_params(colors=text_color)
            axes[0].legend(frameon=False, loc="upper right", fontsize=10, facecolor=background_color,
                           labelcolor=text_color)

            # Chart 2: Player Rating History
            axes[1].plot(games, list(reversed(gameStats.playerRankingHistory)), color=rating_color, label="Player Rating",
                         linewidth=2.5)
            axes[1].set_facecolor(background_color)
            axes[1].set_title("Player Rating History", fontsize=14, color=text_color)
            axes[1].set_xlabel("Game", fontsize=12, color=text_color)
            axes[1].set_ylabel("Rating", fontsize=12, color=text_color)
            axes[1].grid(color="white", linestyle="--", alpha=0.2)
            axes[1].tick_params(colors=text_color)
            axes[1].legend(frameon=False, loc="upper right", fontsize=10, facecolor=background_color,
                           labelcolor=text_color)

            # Chart 3: Textual Summary
            axes[4].axis("off")
            summary_text = (
                f"Game Statistics over the last {nr} games:\n\n"
                f"Games won: {len(gameStats.gamesWon)} games:\n"
                f"Games lost {len(gameStats.gamesLost)} games:\n"
                f"Games drawn {gameStats.gamesDrawn} games:\n"
                f"Player average loss: {round(aPlayer.loss, 2)}\n"
                f"Opponent average loss: {round(bPlayer.loss, 2)}\n"
                f"Player ranking performance : {playerPerformance}"
            )
            axes[4].text(0.5, 0.5, summary_text, fontsize=12, ha="center", va="center", color=text_color,
                         bbox=dict(facecolor=background_color, edgecolor="none", boxstyle="round,pad=1"))

            labels = [
                "Much better than opponent",
                "Slightly better than opponent",
                "Similar to opponent",
                "Slightly worse than opponent",
                "Much worse than opponent"
            ]
            sizes = [
                gameStats.muchBetter,
                gameStats.slightBetter,
                gameStats.similar,
                gameStats.slightWorse,
                gameStats.muchWorse
            ]
            colors = ['#dac7cd', '#a3a18a', '#587157', '#3a4a40', '#343e41']

            def format_number(value):
                absolute = int(value / 100 * sum(sizes))
                return f"{absolute}"
            # Create pie chart
            wedges, texts, autotexts = axes[2].pie(
                sizes,
                labels=labels,
                autopct=format_number,
                colors=colors,
                startangle=140,
                textprops=dict(color="white"),
            )

            # Customize text
            for text in texts:
                text.set_color("white")  # Labels
            for autotext in autotexts:
                autotext.set_color("white")  # Percentage values

            # Title
            axes[2].set_title("Game Performance Breakdown", color="white", fontsize=24, fontweight='bold')

            # Background color
            fig.patch.set_facecolor("#303030")
            axes[2].set_facecolor("#303030")

            labels2 = [
                "Won by checkmate",
                "Won by flagging",
                "Lost by checkmate",
                "Lost by flagging",
                "Draw"
            ]
            sizes2 = [
                gameStats.gamesWon.count("Normal"),
                gameStats.gamesWon.count("Time forfeit"),
                gameStats.gamesLost.count("Normal"),
                gameStats.gamesLost.count("Time forfeit"),
                gameStats.gamesDrawn

            ]
            colors2 = ['#ffcab9', '#fca4ab', "#f89d9d", '#f4978e', '#f07080']

            # Create pie chart
            wedges, texts, autotexts = axes[3].pie(
                sizes2,
                labels=labels2,
                autopct=format_number,
                colors=colors2,
                startangle=140,
                textprops=dict(color="white"),

            )

            # Customize text
            for text in texts:
                text.set_color("white")
            for autotext in autotexts:
                autotext.set_color("white")

            # Title
            axes[3].set_title("Game result Breakdown", color="white", fontsize=24, fontweight='bold')

            # Background color
            fig.patch.set_facecolor("#303030")
            axes[3].set_facecolor("#303030")

            # Layout adjustment
            fig.tight_layout(rect=[0, 0, 1, 0.96])


            output_path = f"weekly_report.png"
            plt.savefig(output_path, dpi=600, bbox_inches='tight')





generateRaport(True)
