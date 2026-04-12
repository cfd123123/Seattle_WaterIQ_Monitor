package com.example.waterbusiness.service;

import com.example.waterbusiness.config.WaterAlertProperties;
import com.example.waterbusiness.dto.WaterQualityBatchResponse;
import com.example.waterbusiness.dto.WaterQualityRequest;
import com.example.waterbusiness.dto.WaterQualityResponse;
import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.entity.ModelCallLog;
import com.example.waterbusiness.entity.WaterQualityRecord;
import com.example.waterbusiness.metrics.WaterBusinessMetrics;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.ModelCallLogRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import com.example.waterbusiness.repository.WaterQualityRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import feign.FeignException;
import feign.Request;
import feign.RequestTemplate;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionTemplate;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Consumer;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class WaterQualityServiceTest {

    @Mock
    private WaterQualityRepository waterQualityRepository;
    @Mock
    private ModelCallLogRepository modelCallLogRepository;
    @Mock
    private AlertEventRepository alertEventRepository;
    @Mock
    private WaterBusinessMetrics businessMetrics;
    @Mock
    private AiPredictService aiPredictService;
    @Mock
    private MonitorStationRepository monitorStationRepository;
    @Mock
    private TransactionTemplate txTemplate;

    private WaterQualityService service;

    @BeforeEach
    void setUp() {
        WaterAlertProperties alertProperties = new WaterAlertProperties();
        alertProperties.setThreshold(4);

        service = new WaterQualityService(
                null,
                waterQualityRepository,
                monitorStationRepository,
                modelCallLogRepository,
                alertEventRepository,
                alertProperties,
                new ObjectMapper(),
                null,
                businessMetrics,
                aiPredictService
        );

        // Override transaction template for deterministic unit tests.
        ReflectionTestUtils.setField(service, "requiresNewTx", txTemplate);
        lenient().when(txTemplate.execute(any())).thenAnswer(invocation ->
                ((TransactionCallback<?>) invocation.getArgument(0)).doInTransaction(null));
        lenient().doAnswer(invocation -> {
            invocation.getArgument(0, Consumer.class).accept(null);
            return null;
        }).when(txTemplate).executeWithoutResult(any());

        MonitorStation st = new MonitorStation();
        st.setId(42L);
        st.setStationCode("svc_test_station");
        lenient().when(monitorStationRepository.findByStationCode("svc_test_station"))
                .thenReturn(Optional.of(st));
    }

    @Test
    void checkAndSave_shouldPersistRecordLogAndAlert_whenPredictionIsPoor() {
        WaterQualityRequest request = buildRequest();
        WaterQualityResponse response = new WaterQualityResponse();
        response.setPollutionLevel("Poor");
        when(aiPredictService.predictWithRetry(any())).thenReturn(response);
        when(waterQualityRepository.save(any())).thenAnswer(invocation -> {
            WaterQualityRecord r = invocation.getArgument(0);
            r.setId(1L);
            return r;
        });

        WaterQualityResponse out = service.checkAndSave(request);

        assertEquals("Poor", out.getPollutionLevel());
        verify(waterQualityRepository).save(any(WaterQualityRecord.class));
        verify(modelCallLogRepository).save(any(ModelCallLog.class));
        verify(alertEventRepository).save(any(AlertEvent.class));
        verify(businessMetrics).recordAlertCreated("MEDIUM", "Poor");
    }

    @Test
    void checkAndSave_shouldPersistFailureLogAndRethrow_whenAiCallFails() {
        WaterQualityRequest request = buildRequest();
        FeignException.ServiceUnavailable ex = new FeignException.ServiceUnavailable(
                "503",
                Request.create(Request.HttpMethod.POST, "/predict", Map.of(), new byte[0], StandardCharsets.UTF_8, new RequestTemplate()),
                null,
                Map.of()
        );
        when(aiPredictService.predictWithRetry(any())).thenThrow(ex);

        assertThrows(FeignException.ServiceUnavailable.class, () -> service.checkAndSave(request));

        ArgumentCaptor<ModelCallLog> captor = ArgumentCaptor.forClass(ModelCallLog.class);
        verify(modelCallLogRepository).save(captor.capture());
        assertTrue(!captor.getValue().isSuccess());
        assertEquals(503, captor.getValue().getHttpStatus());
    }

    @Test
    void checkBatch_shouldContinueWhenSingleItemFails() {
        WaterQualityRequest req1 = buildRequest();
        WaterQualityRequest req2 = buildRequest();
        WaterQualityResponse ok = new WaterQualityResponse();
        ok.setPollutionLevel("Good");

        when(aiPredictService.predictWithRetry(any()))
                .thenReturn(ok)
                .thenThrow(new RuntimeException("AI down"));
        when(waterQualityRepository.save(any())).thenAnswer(invocation -> invocation.getArgument(0));

        WaterQualityBatchResponse result = service.checkBatch(List.of(req1, req2));

        assertEquals(1, result.getSuccessCount());
        assertEquals(1, result.getFailCount());
        verify(businessMetrics, times(1)).recordBatchItemSuccess();
        verify(businessMetrics, times(1)).recordBatchItemFailure();
    }

    private static WaterQualityRequest buildRequest() {
        WaterQualityRequest request = new WaterQualityRequest();
        request.setWaterTemperatureC(24.5);
        request.setPH(7.1);
        request.setDissolvedOxygenMgL(6.9);
        request.setConductivityUSCm(305.0);
        request.setTurbidityNTU(4.0);
        request.setNitrateMgL(1.2);
        request.setAmmoniaNMgL(0.18);
        request.setTotalPhosphorusMgL(0.06);
        request.setCodMgL(16.5);
        request.setBodMgL(3.1);
        request.setHeavyMetalsPbUgL(4.2);
        request.setStationCode("svc_test_station");
        return request;
    }
}
