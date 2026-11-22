# What the parlay research says, and what the card does about it

Read in full on 22 Nov 2026 unless marked otherwise.

## Whelan (2026), "The Parlay Puzzle: Expected Utility and Multi-Leg Betting" (UCD working paper)
- New Jersey sportsbooks kept 19.2% of parlay stakes in 2025 against 4.9% on other bets. Parlays
  were 32% of stakes and 65% of sportsbook profit.
- For a bettor with an edge on every leg and CRRA utility, the best leg count depends almost only
  on the geometric-mean leg probability p: singles below 1/3, two legs to 0.53, three to 0.63,
  four to 0.70, five to 0.75, ten from 0.85. Risk aversion and edge size barely move these.
- The median US parlay has five legs, which fits only if legs average 70% or more. Typical
  parlay legs are at or below 50%.
- **Applied:** `football/research_rules.py` solves his eq. A.26 (matches his Table 2 to 0.003).
  Every slip carries a check: legs' geometric mean, the longest slip the rule supports, and
  whether this slip is within it. The "Long shot" tier dropped from fair 7.0 to 5.5, because five
  legs at 68% broke the rule. The 19-leg wildcard is flagged: legs at 90.7% support 16.

## Whelan, "Why Bookmakers Love Multi-Leg Bets" (article)
- Expected payout on N legs is (1 − m)^N: 77c per dollar for five legs at a 5% margin.
- Accumulator "boosts" only slow the decline. A near miss (one leg short) is N times likelier
  than a win at 50% legs and says nothing about the next slip.
- **Applied:** the wildcard cards already used (1 − m)^N. Slips of four or more legs now show how
  often they finish exactly one leg short.

## Long (2026), "Optimal Parlay Wagering and Whitrow Asymptotics" (arXiv 2603.26620)
- Under Kelly staking, the optimal book over all singles and parlays is the outer product of the
  single-event Kelly bets. A parlay is in it only if every leg is worth betting alone.
- Banning parlays costs growth only at fourth order in the edge: singles are nearly as good.
- Confirms Grant, Johnstone & Kwon (2008, *Decision Analysis*, not read: paywalled).
- **Applied:** value mode already requires an edge on each leg (`min_edge`). When odds are
  connected, stake singles by Kelly first and treat parlays as optional.

## Hegarty & Whelan (2023), "Do Gamblers Understand Complex Bets?" (MPRA 117244)
- On Asian handicaps, bettors lose more on lines with no refund than on lines with one, and odds
  do not equalise returns: complexity is priced against the bettor.
- Pinnacle's average margin on European 1X2 was about 3% in 2019-22.
- **Applied:** the card stays on simple markets. Its 5% per-leg margin is a retail assumption;
  a sharp book is nearer 3%.

## Goddard & Asimakopoulos, "Modelling football match results and the efficiency of fixed-odds betting"
- Ordered probit on 15 years of English results. Beyond past results, match significance for
  end-of-season outcomes, cup involvement, distance and attendance all added to the model.
- Bets in the top 15% by model expected return made at least +4% in each of four seasons; the
  bottom 30% lost 14-17%. Inefficiencies shrank over time.
- **Applied / open:** ranking by expected return against bookmaker odds is what value mode does.
  Distance did not help in our 2023-26 test. Match significance late in the season is untested
  here and worth trying in spring.

## Not read
- Hegarty & Whelan, CEPR DP17948 (margins higher on longshots): the PDF returned 403.
- "How bookies make your money" (*Judgment and Decision Making*): host unreachable.
- Zafiris (2014), Whitrow (2007), Dixon & Coles (1997), Grant et al. (2008): paywalled.
