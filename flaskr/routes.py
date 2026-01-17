from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask import current_app
from .models import Game, Player
from flaskr import socketio

import random
import time

bp = Blueprint('routes', __name__, template_folder="templates")
# in-memory storage of active games
active_games = {}
# storage of active turn flags. False = Running. True = Needs to stop.
stop_turn_events = {}
# debugging variable only. change to make timer during rounds speed up or slow down. Timer in seconds.
TIMER_LENGTH = .3

@bp.route('/')
def lobby():
    # lobby where players enter a game and pick a team
    return render_template('lobby.html')

@bp.route('/catherine', methods=["POST", "GET"])
def catherine():
    answer_correct = False
    has_attempted = False
    if request.method == "POST":
        cryptic_answer: str = str(request.form["answer"]).lower().strip()
        has_attempted = True  # add "Try Again!" text from front end if the answer isn't correct
        if cryptic_answer == "for shrimp":
            has_attempted = False  # remove "Try Again!" text from front end
            answer_correct = True

    return render_template('catherine.html',
                           answer_correct=answer_correct,
                           has_attempted=has_attempted)

@bp.route("/join", methods=["POST"])
def join_game():
    player_name = request.form["player_name"]
    game_id = request.form["game_id"]
    team_name = request.form["team_name"]

    # Create a new game if it doesn't exist
    if game_id not in active_games:
        active_games[game_id] = Game(session_id=game_id)
    
    game:Game = active_games[game_id]

    # check that name has not already been used. if so, just add a number at the end
    count = 2
    final_name = player_name
    while final_name in [_ for _ in list(game.players.keys())]:
        final_name = player_name + " " + str(count)
        count += 1
    # Create player and assign to team
    player = Player(name=final_name, team=team_name)
    game.add_player(player)

    # Redirect to draw cards page
    return redirect(url_for("routes.draw_cards", 
                            game_id=game_id, 
                            player_name=final_name))

@bp.route("/draw", methods=["GET", "POST"])
def draw_cards():
    game_id = request.args.get("game_id")
    player_name = request.args.get("player_name")

    game = active_games.get(game_id)
    if not game:
        print(f"\n\n\tGAME NOT FOUND FOR {game_id}\n\n")
        return "Game not found", 404

    player = game.players.get(player_name)
    if not player:
        return "Player not found", 404

    # Handle refresh or submission
    if request.method == "POST":
        if "refresh" in request.form:
            game.refresh_hand_for_player(player)
        elif "custom" in request.form:
            term = request.form.get("term")
            definition = request.form.get("definition")
            points = int(request.form.get("points"))
            custom_card = {
                "term": term,
                "definition": definition,
                "points": points
            }
            player.submitted.append(custom_card)
            game.game_pool.append(custom_card)
            flash("Custom card submitted!")
            if len(player.submitted) < 6:
                flash(f"Please select {6-len(player.submitted)} more cards!")
                return render_template("draw_cards.html",
                        game_id=game_id,
                        player_name=player_name,
                        hand=player.hand)
            else:
                return redirect(url_for("routes.waiting_for_others",
                                        game_id=game_id,
                                        player_name=player_name))
        elif "submit" in request.form:
            selected_cards = request.form.getlist("card")
            if len(selected_cards) > 6 - len(player.submitted):
                flash(f"Please select up to {6-len(player.submitted)} cards to submit or press refresh to get new cards.")
            else:
                # Map selected terms to actual card objects
                card_objects = [card for card in player.hand if card["term"] in selected_cards]
                player.submitted.extend(card_objects)
                game.game_pool.extend(card_objects)
                flash("Cards submitted to game pool!")

                if len(player.submitted) < 6:
                    flash(f"Please select {6-len(player.submitted)} more cards!")
                    left_over = [card for card in player.hand if card["term"] not in selected_cards]
                    game.draw_cards_for_player(player, len(selected_cards))
                    player.hand.extend(left_over)
                    return render_template("draw_cards.html",
                           game_id=game_id,
                           player_name=player_name,
                           hand=player.hand)
                else:
                    return redirect(url_for("routes.waiting_for_others",
                                            game_id=game_id,
                                            player_name=player_name))

    # Initial draw if hand is empty
    if not player.hand:
        game.draw_cards_for_player(player)

    return render_template("draw_cards.html",
                           game_id=game_id,
                           player_name=player_name,
                           hand=player.hand)

@bp.route("/waiting_for_others")
def waiting_for_others():
    '''For when you've submitted your cards and are waiting for other players'''
    game_id = request.args.get("game_id")
    player_name = request.args.get("player_name")

    game = active_games.get(game_id)
    if not game:
        return "Game not found", 404

    return render_template("waiting_for_others.html",
                           game_id=game_id,
                           player_name=player_name)

@bp.route("/api/check_submissions")
def api_check_submissions():
    game_id = request.args.get("game_id")
    game = active_games.get(game_id)

    if not game:
        return {"error": "not_found"}, 404
    
    player_names = [p.name + " is on Team " + p.team for p in game.players.values() if len(p.submitted) == 6]

    return {"all_submitted": game.all_players_submitted(), "players": player_names}

@bp.route("/start_round")
def start_round_page():
    '''What happens during the redirect from waiting_for_others'''
    game_id = request.args.get("game_id")
    game: Game = active_games.get(game_id)
    if not game:
        return "Game not found", 404
    
    player_name = request.args.get("player_name")

    first_team_name, actor_name = game.current_actor()
    # every teammate of the actor who's going to be guessing next
    actor_teammates = [p.name for p in game.teams[first_team_name].members if p.name != actor_name]
    # map each player to their team name to display in front end separate from acting team name
    player_map = {p.name: p.team for p in game.players.values()}

    return render_template("round.html",
                           game_id=game_id,
                           team_name=first_team_name,
                           actor_name=actor_name,
                           player_name=player_name,
                           player_map=player_map,
                           guesser_names=actor_teammates,
                           round_number=game.current_round,
                           game_pool=game.active_pool,
                           first_term=game.active_pool[0]["term"],
                           first_def=game.active_pool[0]["definition"],
                           first_points=game.active_pool[0]["points"],
                           time=game.turn_time_left)

@socketio.on("start_round")
def socket_start_round(data):
    '''Starts a round during the game'''
    game_id = data.get("game_id")
    game = active_games.get(game_id)
    if not game:
        return
    
    player_name = data.get("player_name")

    game.start_round()
    # save up memory
    game.remaining_cards = []

    first_team_name, actor_name = game.current_actor()
    print(f"\n\n\n\t[DEBUG] Starting round for game {game_id}, current_actor={first_team_name+"; "+actor_name}\n\n\n")

    # Start turn loop as background task
    socketio.start_background_task(start_turn, game_id)

    socketio.emit("round_started", {
        "round_number": game.current_round,
        "active_pool_length": len(game.active_pool),
        "team_name": first_team_name,
        "actor_name": actor_name,
        "player_name": player_name,
    }, room=game_id)

@socketio.on("join_game_room")
def handle_join(data):
    game_id = data["game_id"]
    join_room(game_id)
    # emit("player_joined", {"player_name": data["player_name"]}, room=game_id)

@socketio.on("get_card")
def handle_get_card(data):
    game_id = data["game_id"]
    actor_name = data["actor_name"]
    card_term = data["card_term"]

    game = active_games.get(game_id)
    if not game:
        return

    card = next((c for c in game.active_pool if c["term"] == card_term), None)
    if card:
        game.active_pool.remove(card)
        game.cards_guessed += 1
        team_name = game.players[actor_name].team
        game.teams[team_name].score += card["points"]

    if game.is_round_over():
        scores_string = ""
        for team, score in {t: game.teams[t].score for t in game.teams}.items():
            scores_string += "The " + team + " have " + str(score) + " points! "
        socketio.emit("turn_ended", {
            "actor_name": actor_name,
            "team_name": team_name,
            "time_left": game.turn_time_left
        }, room=game_id)
        if game.current_round < game.total_rounds:
            socketio.emit("round_over", {"scores": scores_string}, room=game_id)
    
    socketio.emit("update_game_state", {
        "game_pool": game.active_pool,
        "guessed_count": game.cards_guessed
    }, room=game_id)
    
@socketio.on("skip_card")
def handle_skip_card(data):
    '''For when a team can't get a card and skips it'''
    game_id = data["game_id"]
    card_term = data["card_term"]

    game = active_games.get(game_id)
    if not game:
        return

    # Move card to end of the pool
    card = next((c for c in game.active_pool if c["term"] == card_term), None)
    if card:
        game.active_pool.remove(card)
        game.active_pool.append(card)

    # Broadcast updated pool
    emit("update_game_state", {"game_pool": game.active_pool, "guessed_count": game.cards_guessed}, room=game_id)

@socketio.on("start_next_turn")
def handle_start_next_turn(data):
    '''Function that starts the next turn mid-round, not at the start of a round'''
    game_id = data["game_id"]
    game = active_games.get(game_id)
    if not game:
        return
    
    # check if there is an active turn in this game
    if game_id in stop_turn_events:
        stop_turn_events[game_id] = True
        socketio.sleep(.9)

    game.next_turn()
    game.paused = False
    socketio.start_background_task(start_turn, game_id)

def start_turn(game_id):
    """
    Background task that runs the full round: iterates turns until active_pool is empty
    (round over). Emits socket events for clients to update UI.
    """
    game = active_games.get(game_id)
    if not game:
        return
    
    # set new flag saying the turn should not be stopped
    stop_turn_events[game_id] = False

    # reset guessed count
    game.cards_guessed = 0
    
    socketio.emit("update_game_state", {
        "game_pool": game.active_pool,
        "guessed_count": game.cards_guessed
    }, room=game_id)

    # Get current actor/team for this turn while starting the next turn
    team_name, actor_name = game.current_actor()
    # every teammate of the actor who's going to be guessing next
    actor_teammates = [p.name for p in game.teams[team_name].members if p.name != actor_name]

    # Announce the turn started
    socketio.emit("turn_started", {
        "team_name": team_name,
        "actor_name": actor_name,
        "time_limit": game.turn_time_left,
        "guesser_names": actor_teammates
    }, room=game_id)

    # Initialize timer
    socketio.emit("update_timer", {
        "time_left": game.turn_time_left,
        "actor_name": actor_name,
        "team_name": team_name
    }, room=game_id)

    # Per-second timer loop for this turn
    while game.turn_time_left > 0 and not game.is_round_over():
        # check if game is paused. If so, do not update timer.
        if game.paused:
            socketio.sleep(0.3)
            continue

        socketio.emit("update_timer", {
            "time_left": game.turn_time_left,
            "actor_name": actor_name,
            "team_name": team_name
        }, room=game_id)

        game.turn_time_left -= 1

        socketio.sleep(TIMER_LENGTH)

    socketio.emit("turn_ended", room=game_id)
    # If the round ended while this turn was running, handle round end
    if game.is_round_over():
        # If you want to automatically start next round (if any), do it here:
        if game.current_round < game.total_rounds:
            # increment round and initialize active_pool for next round
            game.current_round = getattr(game, "current_round", 1) + 1
            socketio.emit("round_ready", {
                "round_number": game.current_round,
            }, room=game_id)
        else:
            # Game completely finished
            scores = {t: game.teams[t].score for t in game.teams}
            scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
            # for debugging only
            if len(scores) == 1:
                scores.append(["Testing Team", 12])
            socketio.emit("game_over", {
                        "redirect_url": f"/game_over/{game_id}/{scores[0][0]}/{scores[0][1]}/{scores[1][0]}/{scores[1][1]}"
                    }, room=game_id)

    # background task exits cleanly here
    return

@socketio.on("pause_round")
def pause_round(data):
    game = active_games[data["game_id"]]
    game.paused = True
    socketio.emit("update_pause", room=data["game_id"])

@socketio.on("resume_round")
def resume_round(data):
    game = active_games[data["game_id"]]
    game.paused = False
    socketio.emit("update_pause", room=data["game_id"])

@socketio.on("lobby_return")
def lobby_return(data):
    '''Returns user to lobby and deletes active game if the last user in the game'''
    game_id = data["game_id"]
    k1 = list(active_games[game_id].players.keys())[0]
    del_player = active_games[game_id].players.pop(k1)
    del del_player
    print(active_games[game_id].players)
    if not active_games[game_id].players:  # no players left
        # remove from list of active games
        curr_game = active_games.pop(game_id, None)
        del curr_game
        print(active_games)

    emit("redirect_to_lobby", {
        "url": url_for("routes.lobby")
    })

@bp.route("/game_over/<game_id>/<team_1>/<int:score_1>/<team_2>/<int:score_2>")
def game_over(game_id, team_1, score_1, team_2, score_2):
    return render_template(
        "game_over.html",
        game_id=game_id,
        team_1=team_1,
        score_1=score_1,
        team_2=team_2,
        score_2=score_2
    )

