# rsync cheat-sheet

```
-a: -rlptD

-r, --recursive             recurse into directories
-l, --links                 copy symlinks as symlinks
-p, --perms                 preserve permissions
-t, --times                 preserve modification times
-J, --omit-link-times       omit symlinks from --times
--chown=USER:GROUP          simple username/groupname mapping

-g, --group                 preserve group
-o, --owner                 preserve owner (super-user only)

-D                          same as --devices --specials
    --devices               preserve device files (super-user only)
    --specials              preserve special files

-v, --verbose               increase verbosity
-u, --update                skip files that are newer on the receiver

-H, --hard-links            preserve hard links
```
