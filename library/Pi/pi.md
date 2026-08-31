# HP-41C Extended Precision PI Program
### originally by Ron Knapp
### PPC Calculator Journal Vol 7 No 5 Pg 10 June 1980

Calculates Pi to arbitrary precision. To use it, enter the number of desired
digits in X and execute the program. Can calculate Pi to 30 digits in 2 minutes
on an original HP41C/CV/CX, 90 places in 9 minutes, 1000 places in 11.5 hours,
1160 places in 15.25 hours.

pi-t is a slightly modified from the original version that puts the start and
stop times in a small XM data file called "TIMES". get-t parses the XM data
file and reports the number of seconds it took to run pi-t.

On the DM41L running at 48 MHz:
| # of digits | Approximate time |
|--|--|
| 10 | 14s |
| 30 | 45s |
| 90 | 207s | 
| 200 | 13m |
| 500 | 1h 10m |
| 1000 | ??? |
