$targets = @(
    'gpt_researcher/retrievers/bing',
    'gpt_researcher/retrievers/brave',
    'gpt_researcher/retrievers/google',
    'gpt_researcher/retrievers/tavily',
    'gpt_researcher/retrievers/serpapi',
    'gpt_researcher/retrievers/serper',
    'gpt_researcher/retrievers/exa',
    'gpt_researcher/retrievers/bocha',
    'gpt_researcher/retrievers/xquik',
    'gpt_researcher/retrievers/groundroute',
    'gpt_researcher/retrievers/nodeseek',
    'gpt_researcher/retrievers/openalex',
    'gpt_researcher/retrievers/semantic_scholar',
    'gpt_researcher/retrievers/custom',
    'gpt_researcher/retrievers/arxiv',
    'gpt_researcher/retrievers/pubmed_central',
    'gpt_researcher/retrievers/hellogithub',
    'gpt_researcher/retrievers/weatheralarm',
    'gpt_researcher/retrievers/earthquake',
    'gpt_researcher/retrievers/history',
    'gpt_researcher/retrievers/mcp',
    'gpt_researcher/vector_store',
    'gpt_researcher/llm_provider/image',
    'gpt_researcher/skills/image_generator.py',
    'gpt_researcher/mcp',
    'gpt_researcher/scraper/browser',
    'gpt_researcher/scraper/firecrawl',
    'gpt_researcher/scraper/pymupdf',
    'gpt_researcher/scraper/tavily_extract',
    'gpt_researcher/scraper/web_base_loader',
    'gpt_researcher/skills/deep_research.py',
    'backend/memory',
    'backend/report_type/deep_research',
    'gpt_researcher/memory/embeddings.py'
)
$deleted = 0; $failed = 0; $skipped = 0
foreach ($t in $targets) {
    if (Test-Path $t) {
        try { Remove-Item -Recurse -Force $t; Write-Host "DELETED: $t"; $deleted++ }
        catch { Write-Host "FAILED: $t - $_"; $failed++ }
    } else {
        Write-Host "SKIP: $t"
        $skipped++
    }
}
Write-Host "---"
Write-Host "Deleted=$deleted Failed=$failed Skipped=$skipped"
