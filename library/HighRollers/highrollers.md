# High Rollers
*From PPC Journal V6N7.*

This is a dice game based on the rules of 
the bonus round of the television game show
High Rollers. For those of us who cannot yet
afford or find extra memory modules this
program fully utilizes the baseic HP 41-C by
using 16 data registers and all of the
remaining program memory.

The object of the game is to eliminate the
numbers 1-9 by correctly using each roll of 
two die. On each turn you can delete any
numbers left that total exactly the sum of
the two die. For example if your roll is 2,4
can eliminate 6, or 5 and 1, or 4 and 2 or 3, 2, and 1.
Any time your roll is doubles you must use that roll
if possible but you also get an extra roll 
that can be used anytime you have no moves
for your current roll.

First, set SIZE to 016 and key in the
program. The first time you run the program
you must XEQ "HR". From then on, if you end
each run normally, the program will turn the
calculator off and when you turn it back on
it automatically starts the game at the
beginning. You are first asked to enter a
six digit fractional seed and then the first
roll is displayed in this format:
a,b:c: 123456789
where a,b: is the roll of
the two die and c: is the number of extra
rolls if you have had any doubles.

Example:
| Display | Action |
|--|--|
| 5, 3: 123456789 | key 8 R/S |
| 6,4: 1234567 9 | key 91 R/S |
| 3, 3: 1: 234567 | key 6 R/S |
| 4,1:1: 2345 7  | key 23 R/S |
| 1,2:1:   45 7 | key 0 R/S |
| 6, 4:    45 7 | key 0 R/S |
| YOU LOSE | |

You must key in 0 when you have no moves. If
you key in numbers that do not total the same
as the two die or numbers that do not show on
the display then the display will co:q
me back
again and you must key in a legal move. One
type of illegal move is possible due to the
limitation of memory. If you have an even
totaled roll such as 4,2 and the 3 has not
been eliminated you can put in the illegal
move of 33 because the game will eliminate
the 3 twice in the same move. Also, although
the rules require that you make a legal move
when possible, you could enter a zero because
the program does not check to see if you have
a legal move. An example is when you have a
roll of 6,1 and the numbers left are 1 34.
Legally you must eliminate 34 and thereby
lose the game even if you have any extra
rolls because a total roll of l is impossible.

After each game the display "CONTINUE?1: NO"
will appear and the program will stop. If
you hit R/S another game will start. If you
key in the number 1 and hit R/S then the
calculator will turn itself off and be
positioned to restart automatically when
turned on.

-- Randal C. Gibson (2075)
