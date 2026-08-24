import sys; sys.path.insert(0, '.')

def result(score, threshold=40):
    return "KEEP" if score >= threshold else "REJECT"

# US10317811B2 (charging member): syn=4, down=5
# Derived attr=115 from: 50+8+115-5-15=153
syn, down, attr = 4, 5, 115
# Signal 5 fires (charging+cartridge in title, not in material title)
centrality_new = max(15, 45)
# DOWNSTREAM + penalty>0 -> attr//2
effective_attr = attr // 2
new_score = 50 + (syn*2) + effective_attr - down - centrality_new
print(f"US10317811B2 (charging member printer): syn={syn} down={down}")
print(f"  Old score: 153")
print(f"  centrality: 15 -> {centrality_new}  attr: {attr} -> {effective_attr}")
print(f"  New score: {new_score} -> {result(new_score)}")

# US9740133B2 (charging member 2): syn=2, down=6, old=131
# borderline branch (down=6 > syn*2=4)
# old: syn*2 + attr - down*3 - penalty = 4+attr-18-15 = 131 -> attr=160
# Signal 5 fires -> penalty=max(15,45)=45, but borderline formula unchanged
syn2, down2, attr2 = 2, 6, 160
penalty2_new = max(15, 45)
new_score2 = (syn2*2) + attr2 - (down2*3) - penalty2_new
print()
print(f"US9740133B2 (charging member 2): syn={syn2} down={down2} (borderline)")
print(f"  Old score: 131")
print(f"  centrality: 15 -> {penalty2_new}")
print(f"  New score (borderline formula): {new_score2} -> {result(new_score2)}")

# EP2522704B1 (adhesive sheet): syn=3, down=4, old=122
# old: 50+6+attr-4-30=122 -> attr=100
# 'adhesive' in title keywords -> Signal 5 fires
syn3, down3, attr3 = 3, 4, 100
penalty3_new = max(30, 45)
effective3 = attr3 // 2
new_score3 = 50 + (syn3*2) + effective3 - down3 - penalty3_new
print()
print(f"EP2522704B1 (adhesive sheet): syn={syn3} down={down3}")
print(f"  Old score: 122")
print(f"  centrality: 30 -> {penalty3_new}  attr: {attr3} -> {effective3}")
print(f"  New score: {new_score3} -> {result(new_score3)}")

# US11131058B2 (transmission belt): syn=4, down=10, old=123
# down=10 > syn*2=8 -> borderline
# old: 8+attr-30-15=123 -> attr=160
# 'belt','transmission' -> Signal 5 -> penalty=max(15,45)=45
syn4, down4, attr4 = 4, 10, 160
penalty4_new = max(15, 45)
new_score4 = (syn4*2) + attr4 - (down4*3) - penalty4_new
print()
print(f"US11131058B2 (transmission belt): syn={syn4} down={down4} (borderline)")
print(f"  Old score: 123")
print(f"  centrality: 15 -> {penalty4_new}")
print(f"  New score (borderline formula): {new_score4} -> {result(new_score4)}")

# GOOD PATENTS - verify no regression
# EP2057205B1: syn=5 (TARGET_TRANSFORMATION), down~2, attr~80, penalty=0, old=194
syn5, down5, attr5 = 5, 2, 80
new_score5 = 50 + (syn5*2) + attr5 - down5 - 0
print()
print(f"EP2057205B1 (legitimate NBR patent): estimated")
print(f"  New score (no change): ~{new_score5} -> {result(new_score5)}")

# US9346908B1: olefin metathesis for low MW, syn=6, down=1, penalty=0
syn6, down6, attr6 = 6, 1, 80
new_score6 = 50 + (syn6*2) + attr6 - down6 - 0
print()
print(f"US9346908B1 (olefin metathesis): estimated")
print(f"  New score (no change): ~{new_score6} -> {result(new_score6)}")
