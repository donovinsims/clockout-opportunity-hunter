// Stable attributes/roles first; observed class fallbacks last. Fixtures are synthetic unless labeled live.
export const SELECTORS = Object.freeze({
  card: 'div.jftiEf[data-review-id]',
  cardFallback: 'div[data-review-id]',
  rating: ['[role="img"][aria-label*="star" i]','[role="img"][aria-label*="Stern" i]','span.kvMYJc','span.fzvQIb'],
  reviewerName: ['[data-reviewer-name]','.d4r55','button[data-href*="contrib/"]','a[href*="contrib/"]'],
  reviewerProfileUrl: ['button[data-href*="contrib/"]','a[href*="contrib/"]'],
  reviewText: ['[data-review-text]','[data-review-body]','.MyEned .wiI7pd','.wiI7pd'],
  ownerResponse: ['[data-owner-response]','[aria-label="Response from the owner"]','.CDe7pd'],
  publishedDateRaw: ['[data-review-date]','time','.rsqaWe'],
  ownerResponseDateRaw: ['[data-owner-response-date]','time','.DZSIDd','.xRkPPb'],
  moreText: 'button[aria-label="See more" i],button[aria-label="Mehr anzeigen" i],button[data-expand-review],button.w8nwRe,button.w8Iiyf',
  reviewsTab: 'button[role="tab"][aria-label*="review" i],button[role="tab"][aria-label*="rezension" i],button[role="tab"][aria-label*="bewertung" i]',
  // Exclude "... mentioned in N reviews" chip buttons: they end in " reviews" but are not the More-reviews disclosure.
  moreReviews: 'button[aria-label^="More reviews" i],button[aria-label$=" reviews" i]:not([aria-label^="Sort" i]):not([aria-label*="mentioned in" i]),button[aria-label^="Weitere Rezensionen" i],button[aria-label$=" Rezensionen" i]:not([aria-label^="Sort" i]):not([aria-label*="erwähnt" i])',
  sortButton: 'button[aria-label*="sort" i]',
  feed: '[role="feed"]',
  placeRating: ['[data-place-rating]','div.F7nice [role="img"][aria-label]','div.F7nice span[aria-hidden="true"]','span.fontDisplayLarge','div.F7nice span[aria-label]'],
});
