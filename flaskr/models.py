import random
import json
from pathlib import Path

from typing import List
import logging

logging.basicConfig(
    filename='game_debug.log',  # file where logs go
    level=logging.DEBUG,        # log all DEBUG+ messages
    format='%(asctime)s %(levelname)s:%(message)s'
)

CARDS_FILE = Path(__file__).parent / "data/cards.json"

TURN_TIME = 63

def load_all_cards():
    with open(CARDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

class Card:
    def __init__(self, term, definition, points):
        self.term = term
        self.definition = definition
        self.points = points
    
    def __repr__(self):
        return f"[\n\'Term\': {self.term} \n\'Definition\': {self.definition} \n\'Points\': {self.points}\n]"
    
class Player:
    def __init__(self, name, team=None):
        self.name = name
        self.team = team
        self.hand: List[Card] = []  # Cards drawn by this player
        self.submitted: List[Card] = []  # Cards submitted to the game pool

    def __repr__(self):
        return f"[\n Name: {self.name}\n Team: {self.team}"

class Team:
    def __init__(self, name):
        self.name = name
        self.members: List[Player] = []
        self.score = 0
    
    def __repr__(self):
        return f"[\n Name: {self.name}\n Members: {[p.name for p in self.members]}\n Score: {self.score}]"

class Game:
    def __init__(self, session_id):
        self.session_id = session_id
        self.players: dict[str, Player] = {}
        self.teams: dict[str, Team] = {}
        self.game_pool: List[Card] = []  # final pool of cards for current game
        self.active_pool: List[Card] = []  # what's changing during a round
        self.remaining_cards = load_all_cards()
        self.turn_order = []      # list of (team_name, actor_name)
        self.current_turn_index = 0
        self.turn_time_left = TURN_TIME  # seconds
        self.scores = {team: 0 for team in self.teams}
        self.total_rounds = 3
        self.current_round = 1
        self.paused = False
        self.cards_guessed = 0

    def add_player(self, player):
        self.players[player.name] = player
        if player.team:
            self.add_team(player.team)
            self.teams[player.team].members.append(player)

    def all_players_submitted(self) -> bool:
        return self.game_pool and (len(self.game_pool) == 6 * len(self.players))

    def add_team(self, team_name):
        if team_name not in self.teams:
            self.teams[team_name] = Team(team_name)
    
    def reorder_teams(self, d: dict):
        '''Moves the first element of a dictionary to the end'''
        key_to_move = list(d.keys())[0]
        val = d.pop(key_to_move)
        d[key_to_move] = val
        for k in d:
            random.shuffle(d[k].members)

    def draw_cards_for_player(self, player, n=12):
        if len(self.remaining_cards) < n:
            raise ValueError("Not enough cards remaining to draw")
        player.hand = random.sample(self.remaining_cards, n)
        # Remove drawn cards from remaining deck
        for card in player.hand:
            self.remaining_cards.remove(card)
    
    def refresh_hand_for_player(self, player: Player):
        # Return previous hand to the remaining deck
        self.remaining_cards.extend(player.hand)
        player.hand = []
        self.draw_cards_for_player(player, n=12-len(player.submitted))

    def setup_turn_order(self):
        """Create a turn order that alternates between teams."""
        # Make a copy of each team's members as queues
        team_queues = {team_name: list(team.members) for team_name, team in self.teams.items() if team.members}
        
        self.turn_order = []

        # Keep looping until all queues are empty
        while any(team_queues.values()):
            for team_name in self.teams:
                if team_name in team_queues and team_queues[team_name]:
                    # Pop the first player from the team's queue
                    player = team_queues[team_name].pop(0)
                    self.turn_order.append((team_name, player.name))
        
        self.current_turn_index = 0

    def start_round(self):
        """Initialize active_pool and turn order for a new round"""
        self.active_pool = self.game_pool.copy()
        random.shuffle(self.active_pool)
        self.reorder_teams(self.teams)
        # self.print_turn_order()
        self.current_turn_index = 0
        self.turn_time_left = TURN_TIME
        self.cards_guessed = 0
    
    def next_turn(self):
        self.current_turn_index += 1
        self.turn_time_left = TURN_TIME
        self.cards_guessed = 0

        if not self.active_pool:
            # End of one round of turns
            self.current_round += 1
            if self.current_round > self.total_rounds or self.is_round_over():
                return None  # game over
            else:
                # start next round
                self.start_round()

        return self.current_actor()
    
    def print_turn_order(self):
        '''debugging method only'''
        for i in range(6):
            team_queues = {j: team for j, team in enumerate(self.teams.values()) if team.members}
            curr_team = team_queues[i % len(team_queues)]
            team_name = curr_team.name
            actor_name = curr_team.members[(i // len(team_queues)) % len(curr_team.members)].name
            print(i, ": ", team_name, "; ", actor_name)
    
    def current_actor(self):
        team_queues = {j: team for j, team in enumerate(self.teams.values()) if team.members}
        curr_team = team_queues[self.current_turn_index % len(team_queues)]
        team_name = curr_team.name
        actor_name = curr_team.members[(self.current_turn_index // len(team_queues)) % len(curr_team.members)].name
        return team_name, actor_name
    
    def is_round_over(self):
        return len(self.active_pool) == 0
    