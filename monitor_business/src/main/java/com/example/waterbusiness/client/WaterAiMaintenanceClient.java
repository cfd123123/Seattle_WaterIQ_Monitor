package com.example.waterbusiness.client;

import com.example.waterbusiness.dto.SiteParamAnomalyIvRequest;
import com.example.waterbusiness.dto.SiteParamAnomalyIvResponse;
import com.example.waterbusiness.dto.SitesWith63680Request;
import com.example.waterbusiness.dto.SitesWith63680Response;
import com.example.waterbusiness.dto.TurbidityThresholdBatchRequest;
import com.example.waterbusiness.dto.TurbidityThresholdBatchResponse;
import com.example.waterbusiness.dto.UsgsIvLatestCoreRequest;
import com.example.waterbusiness.dto.UsgsIvLatestCoreResponse;
import com.example.waterbusiness.dto.UsgsIvPythonRefreshBody;
import com.example.waterbusiness.dto.UsgsIvRefreshResponse;
import com.example.waterbusiness.dto.UsgsSiteVerifyResponse;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

@FeignClient(name = "waterAiMaintenanceClient", url = "${water.ai.base-url:http://localhost:8000}")
public interface WaterAiMaintenanceClient {

    @GetMapping("/usgs/site/{siteNo}/verify")
    UsgsSiteVerifyResponse verifyUsgsSite(@PathVariable("siteNo") String siteNo);

    @PostMapping(value = "/refresh/usgs-iv", consumes = MediaType.APPLICATION_JSON_VALUE)
    UsgsIvRefreshResponse refreshUsgsIv(@RequestBody UsgsIvPythonRefreshBody body);

    @PostMapping(value = "/usgs/iv/latest-core-params", consumes = MediaType.APPLICATION_JSON_VALUE)
    UsgsIvLatestCoreResponse fetchLatestCoreParams(@RequestBody UsgsIvLatestCoreRequest body);

    @PostMapping(value = "/anomaly/site-param-from-iv", consumes = MediaType.APPLICATION_JSON_VALUE)
    SiteParamAnomalyIvResponse anomalySiteParamFromIv(@RequestBody SiteParamAnomalyIvRequest body);

    @PostMapping(value = "/usgs/iv/turbidity-threshold-batch", consumes = MediaType.APPLICATION_JSON_VALUE)
    TurbidityThresholdBatchResponse turbidityThresholdBatch(@RequestBody TurbidityThresholdBatchRequest body);

    @PostMapping(value = "/usgs/iv/sites-with-63680", consumes = MediaType.APPLICATION_JSON_VALUE)
    SitesWith63680Response sitesWith63680(@RequestBody SitesWith63680Request body);
}
