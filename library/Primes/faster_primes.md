# HP-41C Faster Primes Program by Walter Castles
PPC Calculator Journal Vol 7 No 1 P32 Jan 1980

## Original "PR LIST" discussion
If we have the subset of prime numbers, P = p1, p2, ... p(n-1), p(n), then the
integers, n, lying in the interval, P(n-1) to p(n^2) that are relatively
prime to p1, p2, ... p(n-1) are prime. That is, if the integers and
p1*p2...*p(n-1) have a G.C.D. of 1 they are prime. 

The program below uses John Kennedy's G.C.D. program in PPC V6NSP31. As
it is impractical to store all the generated primes, the upper limit, p(n+2),
is undefined and it is necessary to take the square root of all the primes
passod by the G.C.D. Loop to detoraine p(n) and thus the upper linit of the
interval, p(n-1) to p(n^2).

The progran ends with a "NONEXISTANT" error when it runs out of registers to
store the blocks of p,p2....p(n-1) Which must be less than 10^10. However, SIZE
17 will give over 10,000 primes and each additional register will add over
1,000 more.

The algorithm has the advantage that it takes little longer to compute
the primes in a given mmerical interval for the larger primes than for the
smaller. For example, the program gives the primes through 1,033 in 10 minutes
and the primes through 2,819 in 30 minutes. It takes about 1 hour and 40
minutes for the first 1,000 primes.

## Extended version

The extended version of faster_primes, called faster_primes-t, removes the PSE
instructions from the original and uses the TIME and XF modules to calculate
how long the program ran before it ran out of memory. In addition, instead of
simply reporting an error when it runs out of memory, it will stop and display
the last prime it found.
