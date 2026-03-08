import type { MetadataRoute } from 'next'

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: 'https://oni.bot', lastModified: new Date(), changeFrequency: 'weekly', priority: 1 },
    { url: 'https://oni.bot/terms', lastModified: new Date(), changeFrequency: 'monthly', priority: 0.3 },
    { url: 'https://oni.bot/privacy', lastModified: new Date(), changeFrequency: 'monthly', priority: 0.3 },
    { url: 'https://cortex.oni.bot', lastModified: new Date(), changeFrequency: 'weekly', priority: 0.9 },
    { url: 'https://cortex.oni.bot/docs', lastModified: new Date(), changeFrequency: 'weekly', priority: 0.8 },
  ]
}
