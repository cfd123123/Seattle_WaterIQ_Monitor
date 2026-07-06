package com.example.waterbusiness.client;

import com.example.waterbusiness.dto.SiteParamAnomalyIvRequest;
import com.example.waterbusiness.dto.SiteParamAnomalyIvResponse;
import com.example.waterbusiness.dto.SiteParamMultivarAnomalyRequest;
import com.example.waterbusiness.dto.SiteParamMultivarAnomalyResponse;
import com.example.waterbusiness.dto.SitesWith63680Request;
import com.example.waterbusiness.dto.SitesWith63680Response;
import com.example.waterbusiness.dto.CopilotChatRequest;
import com.example.waterbusiness.dto.CopilotChatResponse;
import com.example.waterbusiness.dto.AssistantChatRequest;
import com.example.waterbusiness.dto.AssistantChatResponse;
import com.example.waterbusiness.dto.TurbidityRiskForecast12hRequest;
import com.example.waterbusiness.dto.TurbidityRiskForecast12hResponse;
import com.example.waterbusiness.dto.TurbidityStateSnapshotRequest;
import com.example.waterbusiness.dto.TurbidityStateSnapshotResponse;
import com.example.waterbusiness.dto.TurbidityThresholdBatchRequest;
import com.example.waterbusiness.dto.TurbidityThresholdBatchResponse;
import com.example.waterbusiness.dto.UsgsIvLatestCoreRequest;
import com.example.waterbusiness.dto.UsgsIvLatestCoreResponse;
import com.example.waterbusiness.dto.UsgsIvPythonRefreshBody;
import com.example.waterbusiness.dto.UsgsIvRefreshResponse;
import com.example.waterbusiness.dto.DiscoverPugetSitesRequest;
import com.example.waterbusiness.dto.UsgsSiteVerifyResponse;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

import java.util.Map;

@FeignClient(name = "waterAiMaintenanceClient", url = "${water.ai.base-url:http://localhost:8000}")
public interface WaterAiMaintenanceClient {

    @GetMapping("/config/puget-default-sites")
    Map<String, Object> getPugetDefaultSitesConfig();

    @PostMapping(value = "/maintenance/discover-puget-sites", consumes = MediaType.APPLICATION_JSON_VALUE)
    Map<String, Object> discoverPugetSites(@RequestBody DiscoverPugetSitesRequest body);

    @GetMapping("/usgs/site/{siteNo}/verify")
    UsgsSiteVerifyResponse verifyUsgsSite(@PathVariable("siteNo") String siteNo);

    @PostMapping(value = "/refresh/usgs-iv", consumes = MediaType.APPLICATION_JSON_VALUE)
    UsgsIvRefreshResponse refreshUsgsIv(@RequestBody UsgsIvPythonRefreshBody body);

    @PostMapping(value = "/usgs/iv/latest-core-params", consumes = MediaType.APPLICATION_JSON_VALUE)
    UsgsIvLatestCoreResponse fetchLatestCoreParams(@RequestBody UsgsIvLatestCoreRequest body);

    @PostMapping(value = "/anomaly/site-param-from-iv", consumes = MediaType.APPLICATION_JSON_VALUE)
    SiteParamAnomalyIvResponse anomalySiteParamFromIv(@RequestBody SiteParamAnomalyIvRequest body);

    @PostMapping(value = "/anomaly/site-param-multivar-from-features", consumes = MediaType.APPLICATION_JSON_VALUE)
    SiteParamMultivarAnomalyResponse anomalySiteParamMultivarFromFeatures(
            @RequestBody SiteParamMultivarAnomalyRequest body);

    @PostMapping(value = "/usgs/iv/turbidity-threshold-batch", consumes = MediaType.APPLICATION_JSON_VALUE)
    TurbidityThresholdBatchResponse turbidityThresholdBatch(@RequestBody TurbidityThresholdBatchRequest body);

    @PostMapping(value = "/usgs/iv/sites-with-63680", consumes = MediaType.APPLICATION_JSON_VALUE)
    SitesWith63680Response sitesWith63680(@RequestBody SitesWith63680Request body);

    @PostMapping(value = "/turbidity/state/snapshot", consumes = MediaType.APPLICATION_JSON_VALUE)
    TurbidityStateSnapshotResponse turbidityStateSnapshot(@RequestBody TurbidityStateSnapshotRequest body);

    @PostMapping(value = "/turbidity/risk-forecast-12h", consumes = MediaType.APPLICATION_JSON_VALUE)
    TurbidityRiskForecast12hResponse turbidityRiskForecast12h(@RequestBody TurbidityRiskForecast12hRequest body);

    @PostMapping(value = "/turbidity/risk-explain", consumes = MediaType.APPLICATION_JSON_VALUE)
    TurbidityRiskForecast12hResponse turbidityRiskExplain(@RequestBody TurbidityRiskForecast12hRequest body);

    @PostMapping(value = "/copilot/chat", consumes = MediaType.APPLICATION_JSON_VALUE)
    CopilotChatResponse copilotChat(@RequestBody CopilotChatRequest body);

    @PostMapping(value = "/assistant/chat", consumes = MediaType.APPLICATION_JSON_VALUE)
    AssistantChatResponse assistantChat(@RequestBody AssistantChatRequest body);
}
