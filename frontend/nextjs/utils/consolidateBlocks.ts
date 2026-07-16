export const consolidateSourceAndImageBlocks = (groupedData: any[]) => {
  // Consolidate sourceBlocks — 按 URL 去重，保留第一个（或带有更好 title 的）
  const allSources = groupedData
    .filter(item => item.type === 'sourceBlock')
    .flatMap(block => block.items || []);

  const urlMap = new Map<string, any>();
  for (const src of allSources) {
    if (!src.url) continue;
    const existing = urlMap.get(src.url);
    if (!existing) {
      urlMap.set(src.url, { ...src });
    } else if (src.name && src.name !== src.url && existing.name === existing.url) {
      // 用有意义的名称替换纯 URL 名称
      existing.name = src.name;
    }
  }
  const consolidatedSourceBlock = {
    type: 'sourceBlock',
    items: Array.from(urlMap.values())
  };

  // Consolidate imageBlocks
  const consolidatedImageBlock = {
    type: 'imagesBlock',
    metadata: groupedData
      .filter(item => item.type === 'imagesBlock')
      .flatMap(block => block.metadata || [])
  };

  // Remove all existing sourceBlocks and imageBlocks
  groupedData = groupedData.filter(item => 
    item.type !== 'sourceBlock' && item.type !== 'imagesBlock'
  );

  // Add consolidated blocks if they have items
  if (consolidatedSourceBlock.items.length > 0) {
    groupedData.push(consolidatedSourceBlock);
  }
  if (consolidatedImageBlock.metadata.length > 0) {
    groupedData.push(consolidatedImageBlock);
  }

  return groupedData;
};