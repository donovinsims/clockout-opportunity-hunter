// Use the same OS credential store as the dedicated, manually signed-in Chrome.
// Playwright's mock-keychain/basic-store defaults are inappropriate for this profile.
export const REVIEW_LAUNCH_SECURITY={
  chromiumSandbox:true,
  ignoreDefaultArgs:['--use-mock-keychain','--password-store=basic'],
};
