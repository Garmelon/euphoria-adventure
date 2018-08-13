import asyncio
import configparser
import logging
import os
import pty
import subprocess
import termios
import threading
import tty

import yaboli
from yaboli.utils import *


logger = logging.getLogger("adventure")

class AdventureWrapper:
	ARGS = ["/usr/bin/adventure"]

	def __init__(self):
		self.masterfd, self.slavefd = pty.openpty()
		tty.setraw(self.masterfd, when=termios.TCSANOW)
		#self.wmaster = os.fdopen(self.masterfd, "w")
		#self.rmaster = os.fdopen(self.masterfd, "r")
		self.process = subprocess.Popen(
			self.ARGS,
			stdin=self.slavefd,
			stdout=self.slavefd,
			stderr=self.slavefd,
			bufsize=0,
			#encoding="utf8", text=True
		)

		self.lock = threading.Lock()
		self.lines = []
		self.read_thread = threading.Thread(target=self._run, daemon=True)
		self.read_thread.start()

	def write(self, text):
		os.write(self.masterfd, text.encode("utf8"))

	def enter(self, command):
		self.write(command + "\n")

	def read(self):
		with self.lock:
			lines = self.lines
			self.lines = []
		return b"".join(lines).decode("utf8") # Might result in an exception if in the middle of a character

	def running(self):
		return self.process.poll()

	def _run(self):
		while True:
			#line = self.process.stdout.readline()
			#line = self.process.stdout.read(1)
			try:
				byte = os.read(self.masterfd, 1)
				if not byte: return
			except OSError:
				return
			else:
				with self.lock:
					self.lines.append(byte)

	def stop(self):
		os.close(self.slavefd)
		os.close(self.masterfd)
		#self.master.close()
		self.process.terminate()
		self.process.wait()

class Adventure:
	SHORT_DESCRIPTION = "play the classic text adventure 'adventure'"
	DESCRIPTION = "'adventure' can play the classic text adventure aptly named 'adventure'.\n"
	COMMANDS = (
		"!adventure start|stop|restart - start/stop/restart the adventure\n"
		"!adventure status - check if there's currently an adventure running\n"
		"> your command here - send a command to the adventure, if currently running\n"
	)
	AUTHOR = "Created by @Garmy using github.com/Garmelon/yaboli\n"
	CREDITS = "Uses the 'adventure' program. Thanks to Xyzzy for all the help!\n"

	DELAY = 0.5
	TRIGGER_COMMAND = r">\s*(.*)"

	def __init__(self):
		self.adventures = {}

	@yaboli.command("adventure")
	async def command_adventure(self, room, message, argstr):
		args = yaboli.Bot.parse_args(argstr)

		if len(args) == 1:
			arg = args[0]
			if arg == "start":
				adv = self.adventures.get(room.roomname)
				if adv and adv.running():
					await room.send("Adventure already running.", message.mid)
				else:
					adv = AdventureWrapper()
					self.adventures[room.roomname] = adv
					await room.send("Adventure started.", message.mid)
					await asyncio.sleep(self.DELAY)
					text = adv.read()
					await room.send(text, message.mid)

			elif arg == "stop":
				adv = self.adventures.get(room.roomname)
				if adv and adv.running:
					adv.stop()
					self.adventures.pop(room.roomname)
					await room.send("Adventure stopped.", message.mid)
				else:
					await room.send("Adventure not running.", message.mid)

			elif arg == "restart":
				adv = self.adventures.get(room.roomname)
				if adv and adv.running():
					adv.stop()
					await room.send("Adventure stopped.", message.mid)

				adv = AdventureWrapper()
				self.adventures[room.roomname] = adv
				await room.send("Adventure started.", message.mid)
				await asyncio.sleep(self.DELAY)
				text = adv.read()
				await room.send(text, message.mid)

			elif arg == "status":
				adv = self.adventures.get(room.roomname)
				if adv and adv.running():
					await room.send("Adventure running.", message.mid)
				else:
					await room.send("Adventure not running.", message.mid)

			else:
				text = f"Unknown command: {arg!r}\n{self.COMMANDS}"
				await room.send(text, message.mid)

		else:
			text = "Usage:\n" + self.COMMANDS
			await room.send(text, message.mid)

	@yaboli.trigger(TRIGGER_COMMAND)
	async def trigger_command(self, room, message, match):
		adv = self.adventures.get(room.roomname)

		if not adv:
			await room.send("ERROR: No adventure currently running.", message.mid)
			return

		command = match.group(1).strip()
		if not command:
			await room.send("ERROR: No command.", message.mid)
			return

		adv.enter(command)
		await asyncio.sleep(self.DELAY)
		text = adv.read()

		mid = message.parent if message.parent else message.mid
		await room.send(text, mid)

	async def on_stopped(self, room):
		try:
			adv = self.adventures.pop(room.roomname)
			adv.stop()
		except KeyError:
			pass

class AdventureBot(yaboli.Bot):
	SHORT_HELP = Adventure.SHORT_DESCRIPTION
	LONG_HELP = Adventure.DESCRIPTION + Adventure.COMMANDS + Adventure.AUTHOR + Adventure.CREDITS

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.adventure = Adventure()

	async def on_send(self, room, message):
		await super().on_send(room, message)

		await self.adventure.trigger_command(room, message)

	async def on_command_specific(self, room, message, command, nick, argstr):
		if similar(nick, room.session.nick) and not argstr:
			await self.botrulez_ping(room, message, command)
			await self.botrulez_help(room, message, command, text=self.LONG_HELP)
			await self.botrulez_uptime(room, message, command)
			await self.botrulez_kill(room, message, command)
			await self.botrulez_restart(room, message, command)

	async def on_command_general(self, room, message, command, argstr):
		if not argstr:
			await self.botrulez_ping(room, message, command)
			await self.botrulez_help(room, message, command, text=self.SHORT_HELP)

		await self.adventure.command_adventure(room, message, command, argstr)

	async def on_stopped(self, room):
		await self.adventure.on_stopped(room)

def main(configfile):
	logging.basicConfig(level=logging.INFO)

	config = configparser.ConfigParser(allow_no_value=True)
	config.read(configfile)

	nick = config.get("general", "nick")
	cookiefile = config.get("general", "cookiefile", fallback=None)
	bot = AdventureBot(nick, cookiefile=cookiefile)

	for room, password in config.items("rooms"):
		if not password:
			password = None
		bot.join_room(room, password=password)

	asyncio.get_event_loop().run_forever()

if __name__ == "__main__":
	main("adventure.conf")
