package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.dto.UsgsSiteVerifyResponse;
import feign.FeignException;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
@RequiredArgsConstructor
public class UsgsSiteVerificationService {

    private final WaterAiMaintenanceClient waterAiMaintenanceClient;

    @Value("${water.usgs.verify-external-id-on-save:true}")
    private boolean verifyExternalIdOnSave;

    /**
     * When {@code externalId} is set, resolves site via AI proxy to NWIS; 400 if missing.
     * 502 if AI is unavailable.
     */
    public void requireNwisSiteExistsIfConfigured(String externalId) {
        if (!verifyExternalIdOnSave || externalId == null || externalId.isBlank()) {
            return;
        }
        String siteNo = externalId.trim();
        try {
            UsgsSiteVerifyResponse res = waterAiMaintenanceClient.verifyUsgsSite(siteNo);
            if (res == null || !res.isExists()) {
                String msg = res != null && res.getMessage() != null && !res.getMessage().isBlank()
                        ? res.getMessage()
                        : "USGS（NWIS）中未找到该站点号: " + siteNo;
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, msg);
            }
        } catch (ResponseStatusException e) {
            throw e;
        } catch (FeignException e) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_GATEWAY,
                    "无法通过 AI 服务校验 USGS 站点（请确认 :8000 可用）: " + e.getMessage()
            );
        }
    }
}
