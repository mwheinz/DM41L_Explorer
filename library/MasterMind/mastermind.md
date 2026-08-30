# HP-41C MASTERMIND

- HP-41C MasterMind by Julian Perry
- Datafile V2 N1 Pg 27 Jan-Feb 1983
- Uses: Extended Functions and Time

This short program allows you to play 9 digit master- mind on a basic 41c. The
program is very fast and is only 223 bytes long.

The program listing includes both time madule and X-function instructions but
these can easily be removed(see below).

## INSTRUCTIONS

1. XEQ "MMIND"
2. You will then be prompted by "DIGITS?, 1-9" Enter the code length then press
   R/S.
3. Next you will see "MAX. VALUE?" Enter the maximum value of each digit in the
   code then press R/S.
4. You will then be prompted by "GUESS?" Enter your guess containing the digits
   from 0 to the maximum value, and then press R/S. If you key in a guess which
   is too long the first digits will be lost, and if you do not key in enough
   the guess will be padded with zeros on the left hand side.
5. The program will then return your guess followed by a dash and two other
   digits(eg. #12345-2.1") The first digit inicates the number of correctly
   placed digits in your guess and the second indicates the number of digits
   in your guess that are in the code, but are in the wrong place
   (corresponding to black and white key pegs.
6. Enter your next guess and press R/S. Don't take too long because if you've
   got the time module you are being timed).
7. Keep guessing until you get all of the digits in the right place, when this
   happens you will be told how many attempts you made and if you press R/S you
   will see how much think time you used.

## NOTES:

### X-Functions Module
If you do not have an X-functions module then delete lines 2 and 3, and change
lines 96-99 to:
```
96 "ABCD"
97 ARCL 12
98 ASHF.
```

### Time Module
If you do not have a time module, delete lines 5,6,7,26,27,28,29,36,38 and
113-119. Also few lines to prompt for a seed for the random number generator.

### Synthetic Instructions
Line 35 is TONE P (120)
Line 40 is STO N
Line 47 is STO M
Line 57 is RCL M
Line 62 is STO M
Lines 68 and 70 are NOPs (text 0)
Line 75 is DSE N
