// Splits connection settings. Both values are safe to publish: the publishable key
// only works together with the database's row-level security, which limits every
// signed-in person to their own rows. The daily Garmin sync reads these too.
window.SPLITS_CONFIG = {
  url: "https://lvaxrikegqknfkzrvmbr.supabase.co",
  key: "sb_publishable_A_Mn1IHTHj8uV_e2ut0LXw_wGg8qfsA"
};
