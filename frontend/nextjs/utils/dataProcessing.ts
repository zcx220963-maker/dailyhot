import { Data } from '../types/data';
import { consolidateSourceAndImageBlocks } from './consolidateBlocks';

export const preprocessOrderedData = (data: Data[]) => {
  let groupedData: any[] = [];
  let currentAccordionGroup: any = null;
  let currentSourceGroup: any = null;
  let currentReportGroup: any = null;
  let finalReportGroup: any = null;
  let sourceBlockEncountered = false;
  let lastSubqueriesIndex = -1;
  const seenUrls = new Set<string>();
  // console.log('websocket data before its processed',data)

  data.forEach((item: any) => {
    const { type, content, metadata, output, link } = item;

    if (type === 'question') {
      groupedData.push({ type: 'question', content });
    } else if (type === 'report') {
      // Start a new report group if we don't have one
      if (!currentReportGroup) {
        currentReportGroup = { type: 'reportBlock', content: '' };
        groupedData.push(currentReportGroup);
      }
      currentReportGroup.content += output;
    } else if (type === 'report_complete') {
      // Replace entire report content with the complete version (includes images)
      if (currentReportGroup) {
        currentReportGroup.content = output;
      } else {
        currentReportGroup = { type: 'reportBlock', content: output };
        groupedData.push(currentReportGroup);
      }
    } else if (content === 'selected_images') {
      groupedData.push({ type: 'imagesBlock', metadata });
    } else if (type === 'logs' && content === 'research_report') {
      if (!finalReportGroup) {
        finalReportGroup = { type: 'reportBlock', content: '' };
        groupedData.push(finalReportGroup);
      }
      finalReportGroup.content += output.report;
    } else if (type === 'langgraphButton') {
      groupedData.push({ type: 'langgraphButton', link });
    } else if (type === 'chat') {
      groupedData.push({ type: 'chat', content: content });
    } else {
      if (currentReportGroup) {
        currentReportGroup = null;
      }

      if (content === 'subqueries') {
        if (currentAccordionGroup) {
          currentAccordionGroup = null;
        }
        // 保留 currentSourceGroup 引用，让后续来源继续添加到同一组
        if (currentSourceGroup && currentSourceGroup.items.length > 0 && !groupedData.includes(currentSourceGroup)) {
          groupedData.push(currentSourceGroup);
          sourceBlockEncountered = true;
        }
        groupedData.push(item);
        lastSubqueriesIndex = groupedData.length - 1;
      } else if (type === 'sourceBlock') {
        currentSourceGroup = item;
        if (lastSubqueriesIndex !== -1) {
          groupedData.splice(lastSubqueriesIndex + 1, 0, currentSourceGroup);
          lastSubqueriesIndex = -1;
        } else {
          groupedData.push(currentSourceGroup);
        }
        sourceBlockEncountered = true;
        currentSourceGroup = null;
      } else if (content === 'added_source_url') {
        if (!currentSourceGroup) {
          currentSourceGroup = { type: 'sourceBlock', items: [] };
        }

        // metadata 可能是字符串（旧格式）或对象（包含 url 和 title）
        let sourceUrl: string | null = null;
        let sourceTitle = "";
        if (typeof metadata === 'object' && metadata !== null) {
          sourceUrl = (metadata as any).url || null;
          sourceTitle = (metadata as any).title || "";
        } else if (typeof metadata === 'string') {
          sourceUrl = metadata;
        }

        // URL 标准化：去掉尾部斜杠和 www. 前缀，用于去重比较
        const normalizeUrl = (u: string) => {
          try {
            const o = new URL(u);
            return (o.host.replace(/^www\./, '') + o.pathname.replace(/\/+$/, '') + o.search).toLowerCase();
          } catch {
            return u.replace(/\/+$/, '').replace(/^www\./i, '').toLowerCase();
          }
        };

        if (!sourceUrl) {
          // skip
        } else if (!seenUrls.has(normalizeUrl(sourceUrl))) {
          // 新 URL：加入列表
          seenUrls.add(normalizeUrl(sourceUrl));
          // 如果没有标题，回退为域名
          if (!sourceTitle) {
            try {
              sourceTitle = new URL(sourceUrl).hostname.replace('www.', '');
            } catch (e) {
              sourceTitle = "未知来源";
            }
          }
          currentSourceGroup.items.push({ name: sourceTitle, url: sourceUrl });
          // 立即推入 groupedData，避免丢失
          if (!groupedData.includes(currentSourceGroup)) {
            groupedData.push(currentSourceGroup);
            sourceBlockEncountered = true;
          }
        } else if (sourceTitle) {
          // 已存在但本次带标题：更新对应条目的 name（跨所有已处理的 sourceBlock 搜索）
          for (const block of groupedData) {
            if (block.type === 'sourceBlock' && block.items) {
              const existing = block.items.find((s: any) => normalizeUrl(s.url) === normalizeUrl(sourceUrl));
              if (existing && existing.name !== sourceTitle) {
                existing.name = sourceTitle;
              }
            }
          }
          // 也在当前组中查找
          if (currentSourceGroup.items) {
            const existing = currentSourceGroup.items.find((s: any) => normalizeUrl(s.url) === normalizeUrl(sourceUrl));
            if (existing && existing.name !== sourceTitle) {
              existing.name = sourceTitle;
            }
          }
        }
      } else if (type !== 'path' && content !== '') {
        if (sourceBlockEncountered) {
          if (!currentAccordionGroup) {
            currentAccordionGroup = { type: 'accordionBlock', items: [] };
            groupedData.push(currentAccordionGroup);
          }
          currentAccordionGroup.items.push(item);
        } else {
          groupedData.push(item);
        }
      } else {
        if (currentAccordionGroup) {
          currentAccordionGroup = null;
        }
        // 不要清空 currentSourceGroup，让跨子查询的来源合并到同一组
        // 最终由 consolidateSourceAndImageBlocks 统一去重合并
        if (currentReportGroup) {
          // Find and remove the previous reportBlock
          const reportBlockIndex = groupedData.findIndex(
            item => item === currentReportGroup
          );
          if (reportBlockIndex !== -1) {
            groupedData.splice(reportBlockIndex, 1);
          }
          currentReportGroup = null;  // Reset the current report group
        }
        groupedData.push(item);
      }
    }
  });

  groupedData = consolidateSourceAndImageBlocks(groupedData);
  return groupedData;
}; 