#HP-41C Tower of Skelos Game by Michael Heinz*
*Originally published in the PPC Calculator Journal V11 N4 Pg 14 May 1984.*

Originally written to fit in an HP41C. Uses synthetic programming to pack the
data into an HP41C's memory. However, this version uses Extended Memory to move
some string constants out of main memory to free up a little space.

# The Tower of Skelos

The Tower of Skelos is an adventure-type game played in a
tower six stories tall, with each floor consisting of an 8x8
grid. You are Draman, a halfling thief who has been placed
under a curse by the evil wizard Kregos. Unless you retrieve
for him a magic book from the abandoned tower within 36 hours,
you will die. Here is what Kregos has told you about the
tower:

1. Each floor is wrapped-around. If you walk off one side of the tower, you will re-appear on the other side.
2. The stairs which lead down out of the first floor are your exit. If you leave without the book, Kregos will let you die.
3. Each floor has two rooms containing enchanted food which has the power to heal wounds. Kregos has also supplied you with two such meals.
4. The tower has "warp" rooms which can teleport you instantly to another location.
5. On each floor there are monstors and treasures. The monsters get fiercer and the treasures get richer as you climb.
6. On the second floor is a glowing sword which you can use to both light your way and fry bad guys.
7. On the fourth floor is a cloak of warping which can negate the warp rooms and even allows you to warp yourself from one place to another. (But only on the same floor.)
8. On the fifth floor is a staff of power for zapping your opponents.
9. On the sixth floor is the book, but it is hidden so that it cannot be seen with the magic sword or your flares.
10. The cloak and the magic sword can be used together to see great distances, but Kregos does not know how. (2026 update: Finding this technique can have a strange effect on time... Easter Egg? Bug? I honestly don't remember... Mike)
11. When you pick up a weapon, it replaces the one you have. So if you get the sword and then get the staff, you can't use the sword to fight. (It can still be used as a light, though.)
12. Some manuvers in the game cost time, others do not. The amount of time taken to perform an action takes into consideration the idea that you are moving very slowly and cautiously.
13. The wounds you receive durinig play are deducted from your "Hit Points". You start the game with 30 HP and you lose some every time you are injured. You may gain points back by eating and resting. If your HP drops to zero, you will die.

During game place, the following keys are redefined:

| Key | Operation | | Key | Operation |
|--|--|--|--|--|
| - | Flare | | 7 | North |
| 8 | Warp | | 9 | Eat |
| + | West | | 4 | Stairs |
| 5 | East | | x | Attack |
| 2 | Pause | | 6 | Rest |
| 3 | HP | | / | Score |
| . | Time | | 1 | South |

North, South, East, and West - DIrection keys. These keys
control movement and the flares/glow sword, moving from one
room to another takes 10 minutes of game time.

Flare - Allows you to see into an adjacent room. When you push
the key you will see "** FLARE **" (or if you have the sword,
"GLOW SWORD"). When you see the message, push a direction key
and you will be shown the room that lies in that direction.
You start with 12 flares. The sword automatically replaces the
flares when you find it. Flares use one game minute.

Stairs - Climb or descend a staircase (if any is present). Uses 10 game minutes.

Warp - Use the warp cloak. If you have the warp cloak, you
will be prompted to enter the x,y coordinates of your
destination. Type the y coordinate, \<ENTER\>, the x coordinate, then \<R/S\>. Uses 5 game minutes.

Eat - Eat one unit of magic food. You start with two meals, and may find more as you play. If you do not have any food, the 41 will reply "HUH?" else you will heal 8 HP worth of your wounds. Uses 30 minutes of game itme.

Rest - Rest for one game hour. Restores 4 HP.

HP - Displays your current hit points.

Time - Displays elapsed game time.

Pause - Stop game. Press \<ON\> to continue.

Score - Displays the current score.

Attack - Fight any monster in the room. Uses one game minute.

## Scoring:

* Killing a monster: 200 points * the floor you're on.
* Finding treasure: 100 points * the floor you're on.
* Food: 100 points
* Sword: 250 points
* Cloak: 500 points
* Staff: 1000 points
* Book: 3000 points, if you escape with it.

## Operating Instructions:
1. Load "TWR", "PK-N", "UP-N", and the ASCII file "TS" (described below)
2. XEQ "TWR"; enter a random seed at the prompt.
3. Initialization will take about 15 miutes. The calculator will turn itself off when it is done.
4. Press <ON> to begin. 'The display should read "THE
TOWER " and beep.
5. After a short pause, the display should then read
"1:00 STAIRS ON". This means you are On the first
floor. location 0,0. There are stairs leading down
from this room.
6) Push a command key.... The calculator will beep when
rcady for your next command.

File "TS" must be in XFM for the program to run.
It occupies 18 registers. Its contents are: "EMPTY".
"STAIRS ON". "STAIRS UP". "WARP", "TREASURE". "FOOD".
"SWORD", "CLOAK", "STAFF", "EMPTY", "SKELETON",
"SPIDER", "WRAITH", "SPECTRE", "GARGOYLE", "DEMON".
