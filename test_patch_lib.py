import whatthepatch

patch_text = """diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 line1
+line2
"""

print("--- Testing whatthepatch parser ---")
try:
    diffs = list(whatthepatch.parse_patch(patch_text))
    print(f"Number of diffs: {len(diffs)}")
    for d in diffs:
        print(f"Header: {d.header}")
        print(f"Changes: {len(d.changes) if d.changes else 0}")
        if d.changes:
            for c in d.changes:
                print(f"  Change: old={c.old}, new={c.new}, line={repr(c.line)}")
except Exception as e:
    print(f"Error parsing: {e}")

print("\n--- Testing malformed patch (missing --git) ---")
patch_text_malformed = """--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,2 @@
 line1
+line2
"""
try:
    diffs = list(whatthepatch.parse_patch(patch_text_malformed))
    print(f"Number of diffs: {len(diffs)}")
    for d in diffs:
        print(f"Header: {d.header}")
except Exception as e:
    print(f"Error parsing: {e}")

print("\n--- Testing malformed patch (wrong counts) ---")
patch_text_wrong_counts = """diff --git a/test.txt b/test.txt
--- a/test.txt
+++ b/test.txt
@@ -1,1 +1,3 @@
 line1
+line2
"""
try:
    diffs = list(whatthepatch.parse_patch(patch_text_wrong_counts))
    print(f"Number of diffs: {len(diffs)}")
    for d in diffs:
        print(f"Header: {d.header}")
        print(f"Changes: {len(d.changes)}")
except Exception as e:
    print(f"Error parsing: {e}")
