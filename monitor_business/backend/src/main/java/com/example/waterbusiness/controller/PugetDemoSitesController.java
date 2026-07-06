package com.example.waterbusiness.controller;

import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.dto.ApiResponse;
import com.example.waterbusiness.dto.DiscoverPugetSitesRequest;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import feign.FeignException;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.ClassPathResource;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.io.InputStream;
import java.util.Map;

/**
 * Proxies Puget demo site config and NWIS discovery from the Python AI service.
 */
@RestController
@RequestMapping("/api/demo")
@RequiredArgsConstructor
@Tag(name = "Puget demo sites", description = "USGS Puget default site list and bbox discovery")
public class PugetDemoSitesController {

    private static final Logger log = LoggerFactory.getLogger(PugetDemoSitesController.class);
    private static final String FALLBACK_RESOURCE = "usgs_puget_default_sites_fallback.json";

    private final WaterAiMaintenanceClient waterAiMaintenanceClient;
    private final ObjectMapper objectMapper;

    @GetMapping("/puget-sites")
    @Operation(
            summary = "List Puget default demo sites",
            description = "Reads ai_service/config/usgs_puget_default_sites.json via the AI service; falls back to a bundled JSON if AI is down."
    )
    public ApiResponse<Map<String, Object>> listPugetSites() {
        try {
            return ApiResponse.ok(waterAiMaintenanceClient.getPugetDefaultSitesConfig());
        } catch (FeignException e) {
            log.warn("AI service unavailable for Puget demo sites (status={}): {}", e.status(), e.getMessage());
            return ApiResponse.ok(readFallbackPugetSites());
        } catch (RuntimeException e) {
            log.warn("Failed to load Puget demo sites from AI: {}", e.toString());
            return ApiResponse.ok(readFallbackPugetSites());
        }
    }

    private Map<String, Object> readFallbackPugetSites() {
        ClassPathResource resource = new ClassPathResource(FALLBACK_RESOURCE);
        try (InputStream in = resource.getInputStream()) {
            return objectMapper.readValue(in, new TypeReference<Map<String, Object>>() {});
        } catch (IOException ex) {
            throw new IllegalStateException("Missing classpath resource " + FALLBACK_RESOURCE, ex);
        }
    }

    @PostMapping(value = "/puget-sites/discover", consumes = MediaType.APPLICATION_JSON_VALUE)
    @Operation(
            summary = "Discover new NWIS IV sites in Puget bbox and merge into config",
            description = "Calls AI POST /maintenance/discover-puget-sites. Requires AI (:8000) and outbound access to waterservices.usgs.gov."
    )
    public ApiResponse<Map<String, Object>> discoverPugetSites(
            @RequestBody(required = false) DiscoverPugetSitesRequest body
    ) {
        DiscoverPugetSitesRequest eff = body != null ? body : new DiscoverPugetSitesRequest();
        return ApiResponse.ok(waterAiMaintenanceClient.discoverPugetSites(eff));
    }
}
