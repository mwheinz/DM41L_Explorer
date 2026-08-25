# PROGRAMMABLE STAR TREK

by John Rausch
-- PPC Calculator Journal V7 N2 P44 Feb-Mar 1980

## INTRODUCTION

There probably isn't a programmable device of
any type on this planet that doesn't have some version of
"STAR TREK" I played around with the HP-65 back in 1974 but
its limited size prevented the development of anything decent.
When the HP-67 came out, Hal Brown (67) wrote a program that
made use of a few programming techniques that caught my eye.
Primarily, the exchanging of identically designated primary
and secondary registers which simplified the individual
routines. I then set about complicating things by allowing two
consecutive commands by each ship. This one change was
significant in terms of command selection strategy. I also
introduced two other commands that allowed an evasive maneuver
to be made which reduced the probability of being hit by enemy
fire and allowed damage The end result was called "STAR FLEET
COMBAT TRAINER" (to distinguish it from Hal's program) and
was published in the PPC Journal (V4N6P25) after a lengthy
period of revision.

I guess what I'm trying to get around to is that it's fairly easy
to write a program to simply perform the various commands, but
it's a real job to get the other guy (the calculator) to put up a
respectable fight. My solution is to give you the opportunity ta
come up with your own cormand selection logic. The Programmable
Star Trek System is basically the same as the Star Fleet Combat
Trainer. One command to provide status on the damage to both
ships, the evasive maneuver percentages, and the range has been
added. In fact It is possible to come up with a much more
elaborate program. In fact, I had photon torpedoes and all kinds
of fancy commands in my first HP-41C version but it was too much
and really didn't add much fun. What I've discovered is that it's
better to have a program (any game program) that is a formidable
opponent yet simple than it is to have a fancy one that is easy
to beat.

The command selection logic initially provided is very similar to that
used by the Star Fleet Combat Trainer. What I propose is a tournament.
Let's see who can come up with the best command selection logic. The
program is written in such a way that the command selection logic can be
used for either ship. In this way a round robin type tournament can be
conducted. Anyone who is interested can send their command selection
logic to me at my new address listed below. I would prefer that it be
sent on a mag card. If you send along a SASE for a couple of ounces, I
will return your card along with the printouts of your rounds. Some
ground rules will have to be established:

1. The conmand logic sequence must not be more than 600 bytes.
This will allow two 600 byte command logic sequence sub-
routines to be in the machine at the same time.
2. Two commands will be executed per sequence.
3. You may use registers 08-09 for scratch and to retain data
from the first command to the second.
4. When flag 05 is set you may use registers 10-12 for permanent
retention of data. When flag 05 is clear you may use regis-
ters 13-15.
5. You may use flags 07-10
6. You must not change registers 00-07. This is called cheating.

## PROGRAMMABLE STAR TREK

The Programmable Star Trek System (hereinafter known as PSTS)
simulates a confrontation in space between the United feder- ation of
Planets starship Enterprise and an unknown Klingon vessel. Six
commands are available for simulation attack, disengage, evade, fire
phaser, repair damage, and report status. The confrontation begins
with the two starships somewhere between 0 and 99 thousand kilometers
apart. As the captain of the Enterprise, you are given the first
opportunity for action. You must select from 1 to 4 commands. The
number of commands depends on how the command logic being used has
been programmed. More about this later. The flag annunciators at the
bottom of the display indicate the number of commands you have
remaining until the klingon command sequence begins. The report
status command is a free command and does not decrement the number of
commands remaining. The command sequences alternate until one of the
starships is destroyed. A unique feature of the PSTS is the
programmability of the com- mand selection logic for either the
Enterprise or the Klingon. It can be programmed to be cautious,
aggressive, or anything you desire. In fact, you can easily have it
play against itself using the same or different command logic for
each ship.

The following is a detailed description of the commands avaílable to
both the Enterprise and Klingon:

### ATTACK
Moves the attacking ship closer to the other ship by up to 10
thousand kilometers. The distance moved is dependent on the damage to
the attacking ship. A ship with no damage can move the maximum of 10
thousand As damage to the attacking ship increases, the maximum distance
that can be moved is decreased accordingly. The attacking ships' damage
units are divided by 2 and used as a reduction percentage. When the
attacking ship closes to within the maximum distance it can move, the
actual distance moved will be random up to random up to the maximum.
This provides a degree of randomness to close-in manuvers.

### DISENGAGE 

Moves the disengaging ship away from the other ship by up to 10 thousand
kilometers. The distance moved is dependant on the damage to the
disengaging ship. A ship with no damage can move the maximum of 10
thousand kilometers. As damage to the disengaging ship increases, the
maximum distance that can be moved is decreased accordingly. The
disengaging ship's damage units are divided by 2 and used as a reduction
percentage.

### EVADE 

Decreases the probability that the evading ship will be hit by phasers
or photon torpedos. The result of an evasive maneuver is a percentage
from 1 to 50. The higher the percentage, the higher the probability of
avoiding being hit. For any command sequence, the results of multiple
evasive maneuvers can be accumulated. Keep in mind that the evasive
maneuver percentage is reset to 0 for each command sequence.
Accumulating evasive maneuver percentages greater than 100 serve no
purpose.

### FIRE PHASER

The phaser has a maximum range of 10 thousand kilometers.
The maximum damage that can be inflicted is 44 units. The maximum damage
is linear over the entire range of 1 to 10. for example, at 5 thousand
kilometers the maximum damage is 24. This can be easily calculated as
follows: damage = 44 - (Range * 4). The actual damage inflicted is
random from 0 to the range dependent maximum. Phasers become inoperable
when the damage to the ship reaches 80 units. When an attacking ship
causes damage to the other ship that is 100 units or greater, that ship
is considered destroyed and the attacking ship is the winner of the
simulated confrontation.

### REPAIR DAMAGE

Repairs damage to the ship up to a maximum of 20
units. The number of units is random.

### STATUS 

Displays the damage and evasive maneuver percnetages for
both ships followed by the range. This command is free.

## Operating Procedure

1. Load the Star Trek main program (ST)
2. Load the Command Logic programs (EL & KL)
3. Press XEQ ALPHA ST ALPHA
4. When prompted for a random number seed, enter a number between 0 and 1 and press R/S.

Initialization is now complete. The first display will show the range between
the ships. This will be followed by the display '*ENTERPRISE*" indicating that
the Enterprise is the active ship. Next you will be prompted for a command with
the display "CMD?". You are now set to select your first command. The number of
commands that you may make before the Klingon begins selecting commands is
shown in the flag annunciators at the hottom of the display. Commands are
selected by entering the command number (shown below). Do not press R/S. After
you have selected the proper number of commands, the Klingon will select the
same number. The cycle continues until one of the ships is destroyed.

| Command | Key | Display |
|--|--|--|
| Attack | 1 | **ATTACK** - Confirmation of command. **RANGE: nnK** - Range in thousands of kilometers. |
| Disengage | 2 | **DISENGAGE** - Confirmation of command. **RANGE: nnK** - Range in thousands of kilometers. |
| Evade | 3 | **EVADE** - Confirmation of command. **PROB: nnn%** - accumulated percent probability that enemy fire will be evaded. |
| Fire Phaser | 4 | **PHASER** - Command confirmation. **OUT OF RANGE** - Range is greater than 10 thousand kilometers **EVADED** - Phaser fire has been evaded by the other ship. **INOPERATIVE** - Phasers are inoperative. **UNITS: nn** - The number of damage units inflicted on the other ship. **DAMAGE: nnn*** - The total damage units for the other ship. **DESTROYED** - The other ship has been destroyed. |
| Repair Damage | 5 | **REPAIR** - Command confirmation. **UNITS: nn** - The number of damage units repaired. **DAMAGE: nn** The total damage units following the repair. |
| Status | 6 | **STATUS** - Command conformation. **DMG nn/nn** - The Damage units for the two ships (active/inactive). **EV% nn/nn** The evasive maneuver percentages for the two ships (active/inactive). **RANGE: nnk** Range in thousands of kilometers | 

## COMMAND SELECTION LOGIC

The main Star Trek program has no logic built into it that determines which
commands should be executed by either the Enterprise or Klingon. Each time a
command is required for either ship a command selection routine is executed to
select an appropriate command. The command selection routine must be present
for both ships. This routine must return in the X register a number from 1 to 6
which represents the command to be executed. O is returned, the main program goes into a pause loop requesting
the command number from the keyboard. Studying steps 31-43 of
the main program should clarify what happens. It is really quite
simple and results in the maximum flexibility.
Also note steps 11-14. These instructions attempt to execute a
routine labeled "IC" to initialize the number of commands to be
allowed for each sequence. If this routine is not present, two
commands will be used. If you choose to supply this routine,
it must return a number from 1 to 4 in the X register.

The register usage is as follows:
| Register | Description |
|--|--|
| ROO | Number of commands per sequence. |
| RO1 | Number of commands remaining in the current sequence. |
| RO2 | Range in thousands of kilometers. |
| RO3 | Damage units for active ship. |
| R04 | Damage units for inactive ship. |
| R05 | Evasive maneuver percentage for active ship. |
| R06 | Evasive maneuver percetage for inactive ship. |
| RO7 | Random number seed. |

Note that it doesn't matter whether the routine being executed
is "EL" (Enterprise Logic) or "KL" (Klingon Logic), the active
ship is always the ship currently selecting a command.

The routine must not use flags 01-06.

All register values (except R07) are integer values.

John Rausch (80)
